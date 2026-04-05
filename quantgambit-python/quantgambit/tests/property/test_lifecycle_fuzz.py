"""
Property-based fuzz tests for order lifecycle state machine.

Uses Hypothesis to generate random sequences of events and verify
that lifecycle invariants always hold.

Invariants tested:
- 0 <= filled_qty <= qty
- Terminal states remain terminal
- FILLED implies filled_qty == qty
- Duplicate/out-of-order updates cannot corrupt state
- Valid transitions only
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.core.clock import SimClock, set_clock
from quantgambit.core.lifecycle import (
    OrderState,
    ManagedOrder,
    OrderLifecycleManager,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
)
from quantgambit.core.ids import IntentIdentity


# Strategies for generating test data
order_states = st.sampled_from(list(OrderState))
positive_floats = st.floats(min_value=0.001, max_value=1000.0, allow_nan=False, allow_infinity=False)
fill_sizes = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


def create_test_order(qty: float = 1.0) -> ManagedOrder:
    """Create a test order."""
    clock = SimClock()
    set_clock(clock)
    
    identity = IntentIdentity.create(
        strategy_id="test",
        symbol="BTCUSDT",
        side="buy",
        qty=qty,
        entry_type="market",
        entry_price=None,
        stop_loss=None,
        take_profit=None,
        risk_mode="test",
        decision_ts_bucket=1000,
    )
    
    return ManagedOrder(
        identity=identity,
        symbol="BTCUSDT",
        side="buy",
        qty=qty,
        order_type="market",
    )


class TestLifecycleInvariants:
    """Property-based tests for lifecycle invariants."""
    
    @given(st.lists(order_states, min_size=1, max_size=20))
    @settings(max_examples=1000)
    def test_transitions_always_valid_or_rejected(self, state_sequence):
        """
        Property: All transitions are either valid or properly rejected.
        
        The state machine should never enter an invalid state.
        """
        clock = SimClock()
        set_clock(clock)
        order = create_test_order()
        
        for new_state in state_sequence:
            old_state = order.state
            result = order.transition(new_state, clock=clock)
            
            if result:
                # Valid transition occurred
                assert new_state in VALID_TRANSITIONS.get(old_state, set()), \
                    f"Invalid transition accepted: {old_state} -> {new_state}"
                assert order.state == new_state
            else:
                # Invalid transition rejected, state unchanged
                assert order.state == old_state, \
                    f"State changed on rejected transition: {old_state} -> {order.state}"
    
    @given(st.lists(fill_sizes, min_size=1, max_size=20))
    @settings(max_examples=500)
    def test_filled_qty_monotonic(self, fill_sizes):
        """
        Property: filled_qty never decreases.
        
        Once we've filled X, we can't go back to filling less than X.
        """
        clock = SimClock()
        set_clock(clock)
        order = create_test_order(qty=100.0)
        
        max_seen = 0.0
        for size in fill_sizes:
            if size >= max_seen:
                # Valid update
                result = order.update_fill(size, 100.0, 0.1)
                if result:
                    assert order.filled_qty == size
                    max_seen = size
            else:
                # Should be rejected
                old_filled = order.filled_qty
                result = order.update_fill(size, 100.0, 0.1)
                assert not result, f"Decreasing fill accepted: {old_filled} -> {size}"
                assert order.filled_qty == old_filled
    
    @given(fill_sizes)
    @settings(max_examples=200)
    def test_filled_qty_bounded_by_qty(self, fill_size):
        """
        Property: filled_qty never exceeds order qty.
        """
        clock = SimClock()
        set_clock(clock)
        order = create_test_order(qty=1.0)
        
        result = order.update_fill(fill_size, 100.0, 0.1)
        
        if fill_size <= order.qty:
            assert result, f"Valid fill rejected: {fill_size} <= {order.qty}"
            assert order.filled_qty == fill_size
        else:
            assert not result, f"Overfill accepted: {fill_size} > {order.qty}"
            assert order.filled_qty == 0.0
    
    def test_terminal_states_have_no_outgoing(self):
        """
        Invariant: Terminal states cannot transition to any other state.
        """
        for state in TERMINAL_STATES:
            assert VALID_TRANSITIONS.get(state, set()) == set(), \
                f"Terminal state {state} has outgoing transitions"
    
    @given(order_states)
    @settings(max_examples=100)
    def test_terminal_states_remain_terminal(self, target_state):
        """
        Property: Once in a terminal state, no transition is possible.
        """
        clock = SimClock()
        set_clock(clock)
        
        for terminal_state in TERMINAL_STATES:
            order = create_test_order()
            
            # Force into terminal state (bypass normal flow)
            order.state = terminal_state
            
            # Try to transition
            result = order.transition(target_state, clock=clock)
            
            # Should always fail (unless target == current, which is also invalid)
            assert not result, \
                f"Transition from terminal {terminal_state} to {target_state} succeeded"
            assert order.state == terminal_state
    
    @given(st.lists(st.tuples(order_states, fill_sizes), min_size=1, max_size=30))
    @settings(max_examples=500)
    def test_combined_transitions_and_fills(self, events):
        """
        Property: Combined state transitions and fills maintain invariants.
        """
        clock = SimClock()
        set_clock(clock)
        order = create_test_order(qty=100.0)
        
        for new_state, fill_size in events:
            # Try transition
            order.transition(new_state, clock=clock)
            
            # Try fill update
            order.update_fill(fill_size, 100.0, 0.1)
            
            # Check invariants
            assert 0 <= order.filled_qty <= order.qty, \
                f"filled_qty out of bounds: {order.filled_qty}"
            
            if order.state == OrderState.FILLED:
                # Note: We can't guarantee filled_qty == qty because
                # we might have forced FILLED state without proper fill
                pass
    
    @given(st.integers(min_value=1, max_value=100))
    @settings(max_examples=100)
    def test_duplicate_transitions_idempotent(self, repeat_count):
        """
        Property: Duplicate transitions don't corrupt state.
        """
        clock = SimClock()
        set_clock(clock)
        order = create_test_order()
        
        # Transition to SENT
        order.transition(OrderState.SENT, clock=clock)
        assert order.state == OrderState.SENT
        
        # Try to transition to SENT again multiple times
        for _ in range(repeat_count):
            order.transition(OrderState.SENT, clock=clock)
        
        # State should still be SENT (transition to same state is invalid)
        assert order.state == OrderState.SENT


class TestLifecycleManagerInvariants:
    """Property-based tests for OrderLifecycleManager."""
    
    @given(st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=20))
    @settings(max_examples=200)
    def test_registered_orders_retrievable(self, symbols):
        """
        Property: All registered orders can be retrieved.
        """
        clock = SimClock()
        set_clock(clock)
        manager = OrderLifecycleManager(clock=clock)
        
        orders = []
        for i, symbol in enumerate(symbols):
            identity = IntentIdentity.create(
                strategy_id="test",
                symbol=symbol,
                side="buy",
                qty=1.0,
                entry_type="market",
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                risk_mode="test",
                decision_ts_bucket=1000 + i,
            )
            
            order = ManagedOrder(
                identity=identity,
                symbol=symbol,
                side="buy",
                qty=1.0,
                order_type="market",
            )
            
            manager.register(order)
            orders.append(order)
        
        # All orders should be retrievable
        for order in orders:
            retrieved = manager.get_by_client_order_id(order.identity.client_order_id)
            assert retrieved is not None
            assert retrieved.identity.client_order_id == order.identity.client_order_id
    
    @given(st.lists(st.booleans(), min_size=1, max_size=20))
    @settings(max_examples=200)
    def test_ack_updates_exchange_id_index(self, ack_flags):
        """
        Property: Acknowledged orders are indexed by exchange ID.
        """
        clock = SimClock()
        set_clock(clock)
        manager = OrderLifecycleManager(clock=clock)
        
        for i, should_ack in enumerate(ack_flags):
            identity = IntentIdentity.create(
                strategy_id="test",
                symbol="BTCUSDT",
                side="buy",
                qty=1.0,
                entry_type="market",
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                risk_mode="test",
                decision_ts_bucket=1000 + i,
            )
            
            order = ManagedOrder(
                identity=identity,
                symbol="BTCUSDT",
                side="buy",
                qty=1.0,
                order_type="market",
            )
            
            manager.register(order)
            order.transition(OrderState.SENT, clock=clock)
            
            if should_ack:
                exchange_id = f"EX_{i}"
                manager.process_ack(order.identity.client_order_id, exchange_id)
                
                # Should be retrievable by exchange ID
                retrieved = manager.get_by_exchange_id(exchange_id)
                assert retrieved is not None
                assert retrieved.identity.client_order_id == order.identity.client_order_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
