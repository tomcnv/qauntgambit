"""
Unit tests for pre-trade gating system types.

Tests:
- MarketSnapshot creation and freezing
- TradeCandidate creation and serialization
- GateDecision structure
- ExitType/ExitDecision classification
"""

import pytest
import time

from quantgambit.deeptrader_core.types import (
    MarketSnapshot,
    TradeCandidate,
    GateDecision,
    ExitType,
    ExitDecision,
)


class TestMarketSnapshot:
    """Tests for frozen MarketSnapshot dataclass."""
    
    def test_create_market_snapshot(self):
        """Should create valid MarketSnapshot."""
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            exchange="bybit",
            timestamp_ns=int(time.time() * 1e9),
            snapshot_age_ms=50.0,
            mid_price=50000.0,
            bid=49999.0,
            ask=50001.0,
            spread_bps=4.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            depth_imbalance=0.0,
            imb_1s=0.1,
            imb_5s=0.05,
            imb_30s=0.02,
            orderflow_persistence_sec=5.0,
            rv_1s=0.01,
            rv_10s=0.005,
            rv_1m=0.003,
            vol_shock=False,
            vol_regime="normal",
            vol_regime_score=0.5,
            trend_direction="up",
            trend_strength=0.3,
            poc_price=49950.0,
            vah_price=50100.0,
            val_price=49800.0,
            position_in_value="inside",
            expected_fill_slippage_bps=2.0,
            typical_spread_bps=3.5,
            data_quality_score=0.95,
            ws_connected=True,
        )
        
        assert snapshot.symbol == "BTCUSDT"
        assert snapshot.mid_price == 50000.0
        assert snapshot.spread_bps == 4.0
        assert snapshot.vol_shock is False
    
    def test_market_snapshot_is_frozen(self):
        """MarketSnapshot should be immutable."""
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            exchange="bybit",
            timestamp_ns=int(time.time() * 1e9),
            snapshot_age_ms=50.0,
            mid_price=50000.0,
            bid=49999.0,
            ask=50001.0,
            spread_bps=4.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            depth_imbalance=0.0,
            imb_1s=0.0,
            imb_5s=0.0,
            imb_30s=0.0,
            orderflow_persistence_sec=0.0,
            rv_1s=0.0,
            rv_10s=0.0,
            rv_1m=0.0,
            vol_shock=False,
            vol_regime="normal",
            vol_regime_score=0.5,
            trend_direction="neutral",
            trend_strength=0.0,
            poc_price=None,
            vah_price=None,
            val_price=None,
            position_in_value="inside",
            expected_fill_slippage_bps=2.0,
            typical_spread_bps=3.5,
            data_quality_score=1.0,
            ws_connected=True,
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            snapshot.mid_price = 51000.0
    
    def test_market_snapshot_to_dict(self):
        """Should convert to dict for telemetry."""
        snapshot = MarketSnapshot(
            symbol="ETHUSDT",
            exchange="bybit",
            timestamp_ns=1234567890000000000,
            snapshot_age_ms=100.0,
            mid_price=3000.0,
            bid=2999.0,
            ask=3001.0,
            spread_bps=6.67,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            depth_imbalance=0.0,
            imb_1s=-0.2,
            imb_5s=-0.15,
            imb_30s=-0.1,
            orderflow_persistence_sec=10.0,
            rv_1s=0.02,
            rv_10s=0.01,
            rv_1m=0.008,
            vol_shock=False,
            vol_regime="high",
            vol_regime_score=0.8,
            trend_direction="down",
            trend_strength=0.5,
            poc_price=3050.0,
            vah_price=3100.0,
            val_price=2950.0,
            position_in_value="inside",
            expected_fill_slippage_bps=3.0,
            typical_spread_bps=5.0,
            data_quality_score=0.9,
            ws_connected=True,
        )
        
        d = snapshot.to_dict()
        
        assert d["symbol"] == "ETHUSDT"
        assert d["mid_price"] == 3000.0
        assert d["spread_bps"] == 6.67
        assert d["imb_5s"] == -0.15
        assert d["trend_direction"] == "down"
    
    def test_market_snapshot_to_dict_includes_amt_fields(self):
        """Should include all AMT fields in to_dict() for telemetry persistence.
        
        Requirements: 6.1, 6.2, 6.3, 6.4
        - poc_price, vah_price, val_price (6.1)
        - position_in_value (6.2)
        - distance_to_poc_bps, distance_to_vah_bps, distance_to_val_bps (6.3)
        - rotation_factor (6.4)
        """
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            exchange="bybit",
            timestamp_ns=1234567890000000000,
            snapshot_age_ms=50.0,
            mid_price=50000.0,
            bid=49999.0,
            ask=50001.0,
            spread_bps=4.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            depth_imbalance=0.0,
            imb_1s=0.1,
            imb_5s=0.05,
            imb_30s=0.02,
            orderflow_persistence_sec=5.0,
            rv_1s=0.01,
            rv_10s=0.005,
            rv_1m=0.003,
            vol_shock=False,
            vol_regime="normal",
            vol_regime_score=0.5,
            trend_direction="up",
            trend_strength=0.6,
            poc_price=49800.0,
            vah_price=50200.0,
            val_price=49400.0,
            position_in_value="above",
            expected_fill_slippage_bps=2.0,
            typical_spread_bps=3.5,
            data_quality_score=0.95,
            ws_connected=True,
            # AMT distance and rotation fields
            distance_to_poc_bps=200.0,
            distance_to_vah_bps=200.0,
            distance_to_val_bps=600.0,
            rotation_factor=5.2,
        )
        
        d = snapshot.to_dict()
        
        # Verify AMT price levels (Requirement 6.1)
        assert d["poc_price"] == 49800.0
        assert d["vah_price"] == 50200.0
        assert d["val_price"] == 49400.0
        
        # Verify position_in_value (Requirement 6.2)
        assert d["position_in_value"] == "above"
        
        # Verify distance fields (Requirement 6.3)
        assert d["distance_to_poc_bps"] == 200.0
        assert d["distance_to_vah_bps"] == 200.0
        assert d["distance_to_val_bps"] == 600.0
        
        # Verify rotation_factor (Requirement 6.4)
        assert d["rotation_factor"] == 5.2
    
    def test_market_snapshot_to_dict_with_none_amt_fields(self):
        """Should handle None AMT price levels in to_dict().
        
        When AMT levels are not available, they should be None in the output.
        Distance and rotation fields should use their default values (0.0).
        """
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            exchange="bybit",
            timestamp_ns=1234567890000000000,
            snapshot_age_ms=50.0,
            mid_price=50000.0,
            bid=49999.0,
            ask=50001.0,
            spread_bps=4.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            depth_imbalance=0.0,
            imb_1s=0.1,
            imb_5s=0.05,
            imb_30s=0.02,
            orderflow_persistence_sec=5.0,
            rv_1s=0.01,
            rv_10s=0.005,
            rv_1m=0.003,
            vol_shock=False,
            vol_regime="normal",
            vol_regime_score=0.5,
            trend_direction="neutral",
            trend_strength=0.0,
            poc_price=None,  # AMT levels not available
            vah_price=None,
            val_price=None,
            position_in_value="inside",  # Default when AMT not available
            expected_fill_slippage_bps=2.0,
            typical_spread_bps=3.5,
            data_quality_score=0.95,
            ws_connected=True,
            # Distance and rotation use defaults when AMT not available
        )
        
        d = snapshot.to_dict()
        
        # AMT price levels should be None
        assert d["poc_price"] is None
        assert d["vah_price"] is None
        assert d["val_price"] is None
        
        # position_in_value defaults to "inside"
        assert d["position_in_value"] == "inside"
        
        # Distance and rotation fields should be 0.0 (defaults)
        assert d["distance_to_poc_bps"] == 0.0
        assert d["distance_to_vah_bps"] == 0.0
        assert d["distance_to_val_bps"] == 0.0
        assert d["rotation_factor"] == 0.0


class TestTradeCandidate:
    """Tests for TradeCandidate dataclass."""
    
    def test_create_trade_candidate(self):
        """Should create valid TradeCandidate."""
        candidate = TradeCandidate(
            symbol="BTCUSDT",
            side="long",
            strategy_id="poc_magnet_scalp",
            profile_id="micro_range_mean_reversion",
            expected_edge_bps=15.0,
            confidence=0.7,
            entry_price=50000.0,
            stop_loss=49800.0,
            take_profit=50300.0,
            max_position_usd=5000.0,
            generation_reason="POC magnet: price below POC",
            snapshot_timestamp_ns=1234567890000000000,
        )
        
        assert candidate.symbol == "BTCUSDT"
        assert candidate.side == "long"
        assert candidate.expected_edge_bps == 15.0
        assert candidate.stop_loss == 49800.0
    
    def test_trade_candidate_to_dict(self):
        """Should convert to dict for telemetry."""
        candidate = TradeCandidate(
            symbol="SOLUSDT",
            side="short",
            strategy_id="mean_reversion_fade",
            profile_id="neutral_market_scalp",
            expected_edge_bps=20.0,
            confidence=0.65,
            entry_price=100.0,
            stop_loss=101.5,
            take_profit=98.0,
            max_position_usd=2000.0,
            generation_reason="Mean reversion: price above POC",
            snapshot_timestamp_ns=1234567890000000000,
        )
        
        d = candidate.to_dict()
        
        assert d["symbol"] == "SOLUSDT"
        assert d["side"] == "short"
        assert d["strategy_id"] == "mean_reversion_fade"
        assert d["expected_edge_bps"] == 20.0
        assert d["confidence"] == 0.65


class TestGateDecision:
    """Tests for GateDecision structured result."""
    
    def test_gate_decision_allowed(self):
        """Should create allowed gate decision."""
        decision = GateDecision(
            allowed=True,
            gate_name="global_gate",
            reasons=[],
            metrics={"spread_bps": 3.5, "min_depth_usd": 50000.0},
        )
        
        assert decision.allowed is True
        assert decision.gate_name == "global_gate"
        assert len(decision.reasons) == 0
    
    def test_gate_decision_rejected(self):
        """Should create rejected gate decision with reasons."""
        decision = GateDecision(
            allowed=False,
            gate_name="candidate_veto",
            reasons=[
                "orderflow_veto_long:imb_5s=-0.65<-0.5",
                "regime_veto:mean_reversion_in_trend",
            ],
            metrics={"imb_5s": -0.65, "trend_strength": 0.75},
        )
        
        assert decision.allowed is False
        assert len(decision.reasons) == 2
        assert "orderflow_veto" in decision.reasons[0]
    
    def test_gate_decision_to_dict(self):
        """Should convert to dict for telemetry."""
        decision = GateDecision(
            allowed=False,
            gate_name="tradeability",
            reasons=["net_edge_too_low:5bps<10bps"],
            metrics={"expected_edge_bps": 12.0, "cost_bps": 7.0, "net_edge_bps": 5.0},
        )
        
        d = decision.to_dict()
        
        assert d["allowed"] is False
        assert d["gate_name"] == "tradeability"
        assert "net_edge_too_low" in d["reasons"][0]


class TestExitClassification:
    """Tests for ExitType and ExitDecision."""
    
    def test_exit_type_values(self):
        """Should have correct exit type values."""
        assert ExitType.SAFETY.value == "safety"
        assert ExitType.INVALIDATION.value == "invalidation"
    
    def test_safety_exit_decision(self):
        """Safety exit should bypass min_hold."""
        decision = ExitDecision(
            should_exit=True,
            exit_type=ExitType.SAFETY,
            reason="hard_stop_hit (pnl=-2.5%)",
            urgency=1.0,
            confirmations=["hard_stop_hit (pnl=-2.5%)"],
        )
        
        assert decision.should_exit is True
        assert decision.exit_type == ExitType.SAFETY
        assert decision.bypasses_min_hold() is True
        assert decision.urgency == 1.0
    
    def test_invalidation_exit_decision(self):
        """Invalidation exit should respect min_hold."""
        decision = ExitDecision(
            should_exit=True,
            exit_type=ExitType.INVALIDATION,
            reason="orderflow_sell_pressure (imb=-0.7)",
            urgency=0.6,
            confirmations=[
                "orderflow_sell_pressure (imb=-0.7)",
                "trend_reversal_short (conf=0.45)",
            ],
        )
        
        assert decision.should_exit is True
        assert decision.exit_type == ExitType.INVALIDATION
        assert decision.bypasses_min_hold() is False
        assert len(decision.confirmations) == 2
    
    def test_no_exit_decision(self):
        """Should handle no-exit decisions."""
        decision = ExitDecision(
            should_exit=False,
            exit_type=ExitType.INVALIDATION,
            reason="insufficient_confirmations",
            urgency=0.0,
            confirmations=["trend_reversal_short (conf=0.35)"],  # Only 1 confirmation
        )
        
        assert decision.should_exit is False
        assert len(decision.confirmations) == 1
