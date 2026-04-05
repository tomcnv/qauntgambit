"""
Execution policy implementations.

Translates position sizing decisions into concrete execution intents.
"""

from typing import List, Optional
from dataclasses import dataclass

from quantgambit.core.decision.interfaces import (
    DecisionInput,
    RiskOutput,
    ExecutionIntent,
    ExecutionPolicy,
)
from quantgambit.core.ids import generate_intent_id, generate_client_order_id


@dataclass
class ProtectiveOrderParams:
    """Parameters for protective orders (SL/TP)."""
    stop_loss_pct: float = 0.01  # 1% stop loss
    take_profit_pct: Optional[float] = None  # None = no TP
    use_bracket: bool = False  # Use bracket/OCO if supported


class MarketExecutionPolicy(ExecutionPolicy):
    """
    Market order execution policy.
    
    Executes with market orders, optionally with protective orders.
    """
    
    def __init__(
        self,
        execution_policy_version_id: str = "market:1.0.0",
        strategy_id: str = "default",
        decision_bucket_ms: int = 1000,  # Time bucket for intent dedup
        protective_params: Optional[ProtectiveOrderParams] = None,
    ):
        """
        Initialize market execution policy.
        
        Args:
            execution_policy_version_id: Version identifier
            strategy_id: Strategy identifier for intent_id generation
            decision_bucket_ms: Time bucket for deduplication
            protective_params: Optional SL/TP parameters
        """
        self._version_id = execution_policy_version_id
        self._strategy_id = strategy_id
        self._bucket_ms = decision_bucket_ms
        self._protective = protective_params
        self._attempt_counter = 0
    
    def build_intents(
        self,
        *,
        risk_out: RiskOutput,
        decision_input: DecisionInput,
    ) -> List[ExecutionIntent]:
        """
        Build execution intents from risk output.
        
        Args:
            risk_out: Risk mapper output with position sizing
            decision_input: Complete decision input
            
        Returns:
            List of execution intents (usually 0-1)
        """
        delta_w = risk_out["delta_w"]
        
        # No action if churn guard blocked or no delta
        if risk_out["churn_guard_blocked"] or abs(delta_w) < 0.0001:
            return []
        
        symbol = decision_input.symbol
        mid = decision_input.book.mid_price
        equity = decision_input.account_equity
        
        if not mid or mid <= 0 or equity <= 0:
            return []
        
        # Convert weight delta to quantity
        # delta_w = (delta_qty * price) / equity
        # delta_qty = delta_w * equity / price
        delta_qty = abs(delta_w * equity / mid)
        
        # Determine side
        side = "BUY" if delta_w > 0 else "SELL"
        
        # Compute protective order prices
        sl_price: Optional[float] = None
        tp_price: Optional[float] = None
        
        if self._protective:
            if side == "BUY":
                sl_price = mid * (1 - self._protective.stop_loss_pct)
                if self._protective.take_profit_pct:
                    tp_price = mid * (1 + self._protective.take_profit_pct)
            else:
                sl_price = mid * (1 + self._protective.stop_loss_pct)
                if self._protective.take_profit_pct:
                    tp_price = mid * (1 - self._protective.take_profit_pct)
        
        # Generate intent_id
        bucket = int(decision_input.ts_mono * 1000 / self._bucket_ms) * self._bucket_ms
        intent_id = generate_intent_id(
            strategy_id=self._strategy_id,
            symbol=symbol,
            side=side,
            qty=delta_qty,
            entry_type="MARKET",
            entry_price=None,
            stop_loss=sl_price,
            take_profit=tp_price,
            risk_mode="default",
            decision_ts_bucket=bucket,
        )
        
        # Generate client_order_id
        self._attempt_counter += 1
        client_order_id = generate_client_order_id(intent_id, self._attempt_counter)
        
        intent = ExecutionIntent(
            intent_id=intent_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type="MARKET",
            qty=delta_qty,
            price=None,
            reduce_only=delta_w * risk_out["w_current"] < 0,  # Reduce if opposite direction
            sl_price=sl_price,
            tp_price=tp_price,
            use_bracket=self._protective.use_bracket if self._protective else False,
            extra={
                "execution_policy_version_id": self._version_id,
                "delta_w": delta_w,
                "mid_price": mid,
            },
        )
        
        return [intent]


class LimitExecutionPolicy(ExecutionPolicy):
    """
    Limit order execution policy.
    
    Places limit orders at a configurable offset from mid.
    """
    
    def __init__(
        self,
        execution_policy_version_id: str = "limit:1.0.0",
        strategy_id: str = "default",
        decision_bucket_ms: int = 1000,
        offset_bps: float = 2.0,  # Offset from mid in basis points
        post_only: bool = True,  # Post-only mode
        protective_params: Optional[ProtectiveOrderParams] = None,
    ):
        """
        Initialize limit execution policy.
        
        Args:
            execution_policy_version_id: Version identifier
            strategy_id: Strategy identifier
            decision_bucket_ms: Time bucket for deduplication
            offset_bps: Price offset from mid in basis points
            post_only: Whether to use post-only orders
            protective_params: Optional SL/TP parameters
        """
        self._version_id = execution_policy_version_id
        self._strategy_id = strategy_id
        self._bucket_ms = decision_bucket_ms
        self._offset_bps = offset_bps
        self._post_only = post_only
        self._protective = protective_params
        self._attempt_counter = 0
    
    def build_intents(
        self,
        *,
        risk_out: RiskOutput,
        decision_input: DecisionInput,
    ) -> List[ExecutionIntent]:
        """
        Build limit order execution intents.
        
        Args:
            risk_out: Risk mapper output
            decision_input: Complete decision input
            
        Returns:
            List of execution intents
        """
        delta_w = risk_out["delta_w"]
        
        if risk_out["churn_guard_blocked"] or abs(delta_w) < 0.0001:
            return []
        
        symbol = decision_input.symbol
        mid = decision_input.book.mid_price
        bid = decision_input.book.best_bid
        ask = decision_input.book.best_ask
        equity = decision_input.account_equity
        
        if not mid or mid <= 0 or equity <= 0:
            return []
        
        # Convert weight delta to quantity
        delta_qty = abs(delta_w * equity / mid)
        
        # Determine side and price
        side = "BUY" if delta_w > 0 else "SELL"
        
        # Compute limit price with offset
        offset_mult = self._offset_bps / 10000
        if side == "BUY":
            # Buy below mid
            price = mid * (1 - offset_mult)
            if bid:
                price = min(price, bid)  # Don't cross the spread
        else:
            # Sell above mid
            price = mid * (1 + offset_mult)
            if ask:
                price = max(price, ask)  # Don't cross the spread
        
        # Compute protective order prices
        sl_price: Optional[float] = None
        tp_price: Optional[float] = None
        
        if self._protective:
            if side == "BUY":
                sl_price = price * (1 - self._protective.stop_loss_pct)
                if self._protective.take_profit_pct:
                    tp_price = price * (1 + self._protective.take_profit_pct)
            else:
                sl_price = price * (1 + self._protective.stop_loss_pct)
                if self._protective.take_profit_pct:
                    tp_price = price * (1 - self._protective.take_profit_pct)
        
        # Generate IDs
        bucket = int(decision_input.ts_mono * 1000 / self._bucket_ms) * self._bucket_ms
        intent_id = generate_intent_id(
            strategy_id=self._strategy_id,
            symbol=symbol,
            side=side,
            qty=delta_qty,
            entry_type="LIMIT" if not self._post_only else "POST_ONLY",
            entry_price=price,
            stop_loss=sl_price,
            take_profit=tp_price,
            risk_mode="default",
            decision_ts_bucket=bucket,
        )
        
        self._attempt_counter += 1
        client_order_id = generate_client_order_id(intent_id, self._attempt_counter)
        
        intent = ExecutionIntent(
            intent_id=intent_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type="POST_ONLY" if self._post_only else "LIMIT",
            qty=delta_qty,
            price=price,
            reduce_only=delta_w * risk_out["w_current"] < 0,
            sl_price=sl_price,
            tp_price=tp_price,
            use_bracket=self._protective.use_bracket if self._protective else False,
            extra={
                "execution_policy_version_id": self._version_id,
                "delta_w": delta_w,
                "mid_price": mid,
                "offset_bps": self._offset_bps,
            },
        )
        
        return [intent]


class ExitOnlyExecutionPolicy(ExecutionPolicy):
    """
    Exit-only execution policy.
    
    Only generates intents to reduce/close positions, never to open.
    """
    
    def __init__(
        self,
        execution_policy_version_id: str = "exit_only:1.0.0",
        strategy_id: str = "exit",
        decision_bucket_ms: int = 1000,
    ):
        """
        Initialize exit-only policy.
        
        Args:
            execution_policy_version_id: Version identifier
            strategy_id: Strategy identifier
            decision_bucket_ms: Time bucket for deduplication
        """
        self._version_id = execution_policy_version_id
        self._strategy_id = strategy_id
        self._bucket_ms = decision_bucket_ms
        self._attempt_counter = 0
    
    def build_intents(
        self,
        *,
        risk_out: RiskOutput,
        decision_input: DecisionInput,
    ) -> List[ExecutionIntent]:
        """
        Build exit-only execution intents.
        
        Only acts when reducing position (delta_w opposite to w_current).
        
        Args:
            risk_out: Risk mapper output
            decision_input: Complete decision input
            
        Returns:
            List of execution intents (only exits)
        """
        delta_w = risk_out["delta_w"]
        w_current = risk_out["w_current"]
        
        # Only exit if we have a position and delta reduces it
        if abs(w_current) < 0.0001:
            return []  # No position to exit
        
        # Check if delta reduces position (opposite signs)
        if delta_w * w_current >= 0:
            return []  # Not a reducing trade
        
        if risk_out["churn_guard_blocked"]:
            return []
        
        symbol = decision_input.symbol
        mid = decision_input.book.mid_price
        equity = decision_input.account_equity
        
        if not mid or mid <= 0 or equity <= 0:
            return []
        
        # Convert weight delta to quantity
        # Only reduce by the delta amount (don't flip position)
        delta_qty = min(abs(delta_w * equity / mid), abs(w_current * equity / mid))
        
        # Exit side is opposite of position
        side = "SELL" if w_current > 0 else "BUY"
        
        # Generate IDs
        bucket = int(decision_input.ts_mono * 1000 / self._bucket_ms) * self._bucket_ms
        intent_id = generate_intent_id(
            strategy_id=self._strategy_id,
            symbol=symbol,
            side=side,
            qty=delta_qty,
            entry_type="MARKET",
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_mode="exit",
            decision_ts_bucket=bucket,
        )
        
        self._attempt_counter += 1
        client_order_id = generate_client_order_id(intent_id, self._attempt_counter)
        
        intent = ExecutionIntent(
            intent_id=intent_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type="MARKET",
            qty=delta_qty,
            price=None,
            reduce_only=True,  # Always reduce-only for exit policy
            sl_price=None,
            tp_price=None,
            use_bracket=False,
            extra={
                "execution_policy_version_id": self._version_id,
                "exit_reason": "signal",
                "w_current": w_current,
            },
        )
        
        return [intent]
