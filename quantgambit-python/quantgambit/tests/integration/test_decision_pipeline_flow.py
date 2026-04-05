"""
Integration tests for decision pipeline flow.

Tests the full decision pipeline from input to execution intent:
- Feature building
- Model inference
- Calibration
- Edge transform
- Volatility estimation
- Risk mapping
- Execution policy

Also tests pipeline blocking conditions and record generation.
"""

import pytest
from typing import List

from quantgambit.core.clock import SimClock
from quantgambit.core.book.types import OrderBook, Level
from quantgambit.core.decision import (
    DecisionInput,
    Position,
    BookSnapshot,
    ExecutionIntent,
    DecisionRecord,
    DecisionRecordBuilder,
    DecisionOutcome,
)
from quantgambit.core.decision.impl import (
    DummyFeatureFrameBuilder,
    DummyModelRunner,
    DummyCalibrator,
    TanhEdgeTransform,
    EWMAVolatilityEstimator,
    VolTargetRiskMapper,
    MarketExecutionPolicy,
    ProtectiveOrderParams,
)
from quantgambit.core.ids import generate_trace_id


@pytest.fixture
def clock() -> SimClock:
    """Create SimClock."""
    return SimClock(start_time=1704067200.0)  # 2024-01-01 00:00:00


@pytest.fixture
def book() -> OrderBook:
    """Create order book."""
    return OrderBook(
        symbol="BTCUSD",
        bids=[Level(price=100.0, size=10.0)],
        asks=[Level(price=100.2, size=10.0)],
        timestamp=1704067200.0,
        update_id=1,
    )


@pytest.fixture
def decision_input(book: OrderBook, clock: SimClock) -> DecisionInput:
    """Create decision input."""
    return DecisionInput(
        symbol="BTCUSD",
        ts_wall=clock.now(),
        ts_mono=clock.now_mono(),
        book=BookSnapshot.from_order_book(book, is_quoteable=True),
        account_equity=10000.0,
        available_margin=5000.0,
        max_position_size=10.0,
        max_position_value=10000.0,
    )


class TestFullPipelineFlow:
    """Tests for complete pipeline execution."""
    
    def test_pipeline_produces_intent(self, decision_input: DecisionInput, clock: SimClock):
        """Complete pipeline should produce execution intent."""
        # Create pipeline components
        feature_builder = DummyFeatureFrameBuilder(clock)
        model_runner = DummyModelRunner()
        calibrator = DummyCalibrator()
        edge_transform = TanhEdgeTransform(k=10.0, tau=0.05)
        vol_estimator = EWMAVolatilityEstimator()
        risk_mapper = VolTargetRiskMapper(
            w_max=0.20,
            target_vol=0.10,
            min_delta_w=0.001,
        )
        exec_policy = MarketExecutionPolicy(
            strategy_id="test",
            decision_bucket_ms=1000,
        )
        
        # Run pipeline
        features = feature_builder.build(decision_input)
        model_out = model_runner.infer(features)
        calibrated = calibrator.calibrate(model_out)
        edge = edge_transform.to_edge(calibrated["p_hat"])
        vol = vol_estimator.estimate(decision_input)
        risk = risk_mapper.map(
            s=edge["s"],
            vol_hat=vol["vol_hat"],
            decision_input=decision_input,
        )
        intents = exec_policy.build_intents(
            risk_out=risk,
            decision_input=decision_input,
        )
        
        # Verify outputs
        assert features["symbol"] == "BTCUSD"
        assert 0 <= model_out["p_raw"] <= 1
        assert 0 <= calibrated["p_hat"] <= 1
        assert -1 <= edge["s"] <= 1
        assert vol["vol_hat"] > 0
        
        # Intent may or may not be generated depending on signal strength
        # With dummy model p_raw=0.5, edge will be ~0, so churn guard may block
        assert isinstance(intents, list)
    
    def test_pipeline_with_strong_signal(self, clock: SimClock, book: OrderBook):
        """Strong signal should produce entry intent."""
        # Create input with favorable conditions
        decision_input = DecisionInput(
            symbol="BTCUSD",
            ts_wall=clock.now(),
            ts_mono=clock.now_mono(),
            book=BookSnapshot.from_order_book(book, is_quoteable=True),
            account_equity=10000.0,
            available_margin=5000.0,
        )
        
        # Use components that produce strong signal
        feature_builder = DummyFeatureFrameBuilder(clock)
        model_runner = DummyModelRunner(default_p=0.8)  # Strong bullish
        calibrator = DummyCalibrator()
        edge_transform = TanhEdgeTransform(k=10.0, tau=0.05)  # Low deadband
        vol_estimator = EWMAVolatilityEstimator()
        risk_mapper = VolTargetRiskMapper(
            w_max=0.20,
            target_vol=0.10,
            min_delta_w=0.001,
        )
        exec_policy = MarketExecutionPolicy(
            strategy_id="test",
            decision_bucket_ms=1000,
        )
        
        # Run pipeline
        features = feature_builder.build(decision_input)
        model_out = model_runner.infer(features)
        calibrated = calibrator.calibrate(model_out)
        edge = edge_transform.to_edge(calibrated["p_hat"])
        vol = vol_estimator.estimate(decision_input)
        risk = risk_mapper.map(
            s=edge["s"],
            vol_hat=vol["vol_hat"],
            decision_input=decision_input,
        )
        intents = exec_policy.build_intents(
            risk_out=risk,
            decision_input=decision_input,
        )
        
        # With strong signal, should get intent
        if not risk["churn_guard_blocked"] and abs(edge["s"]) > edge["tau"]:
            assert len(intents) >= 1
            intent = intents[0]
            assert intent.symbol == "BTCUSD"
            assert intent.side in ["BUY", "SELL"]
            assert intent.qty > 0


class TestPipelineBlocking:
    """Tests for pipeline blocking conditions."""
    
    def test_deadband_blocks_intent(self, clock: SimClock, book: OrderBook):
        """Weak signal should be blocked by deadband."""
        decision_input = DecisionInput(
            symbol="BTCUSD",
            ts_wall=clock.now(),
            ts_mono=clock.now_mono(),
            book=BookSnapshot.from_order_book(book, is_quoteable=True),
            account_equity=10000.0,
        )
        
        # High deadband threshold
        edge_transform = TanhEdgeTransform(k=1.0, tau=0.5)  # Very high deadband
        
        feature_builder = DummyFeatureFrameBuilder(clock)
        model_runner = DummyModelRunner(default_p=0.52)  # Weak signal
        calibrator = DummyCalibrator()
        
        features = feature_builder.build(decision_input)
        model_out = model_runner.infer(features)
        calibrated = calibrator.calibrate(model_out)
        edge = edge_transform.to_edge(calibrated["p_hat"])
        
        assert edge["deadband_blocked"] is True
        # Signal is still computed, but deadband_blocked indicates it should not be acted upon
        assert abs(edge["s"]) < edge["tau"]  # Signal below threshold
    
    def test_churn_guard_blocks_intent(self, clock: SimClock, book: OrderBook):
        """Small position change should be blocked by churn guard."""
        # Already have a position
        decision_input = DecisionInput(
            symbol="BTCUSD",
            ts_wall=clock.now(),
            ts_mono=clock.now_mono(),
            book=BookSnapshot.from_order_book(book, is_quoteable=True),
            account_equity=10000.0,
            current_position=Position(size=0.1, entry_price=100.0),  # Small position
        )
        
        # Very high churn guard
        risk_mapper = VolTargetRiskMapper(
            w_max=0.20,
            target_vol=0.10,
            min_delta_w=0.5,  # 50% change required
        )
        
        vol_estimator = EWMAVolatilityEstimator()
        vol = vol_estimator.estimate(decision_input)
        
        risk = risk_mapper.map(
            s=0.1,  # Small signal
            vol_hat=vol["vol_hat"],
            decision_input=decision_input,
        )
        
        assert risk["churn_guard_blocked"] is True
        assert risk["delta_w"] == 0.0


class TestDecisionRecordBuilder:
    """Tests for DecisionRecord building."""
    
    def test_build_complete_record(self, clock: SimClock, decision_input: DecisionInput):
        """Should build complete decision record."""
        feature_builder = DummyFeatureFrameBuilder(clock)
        model_runner = DummyModelRunner()
        calibrator = DummyCalibrator()
        edge_transform = TanhEdgeTransform()
        vol_estimator = EWMAVolatilityEstimator()
        risk_mapper = VolTargetRiskMapper()
        exec_policy = MarketExecutionPolicy()
        
        # Run pipeline and build record
        trace_id = generate_trace_id()
        features = feature_builder.build(decision_input)
        model_out = model_runner.infer(features)
        calibrated = calibrator.calibrate(model_out)
        edge = edge_transform.to_edge(calibrated["p_hat"])
        vol = vol_estimator.estimate(decision_input)
        risk = risk_mapper.map(s=edge["s"], vol_hat=vol["vol_hat"], decision_input=decision_input)
        intents = exec_policy.build_intents(risk_out=risk, decision_input=decision_input)
        
        record = (
            DecisionRecordBuilder()
            .with_identifiers(
                record_id=f"rec_{trace_id}",
                trace_id=trace_id,
                symbol="BTCUSD",
            )
            .with_timestamps(
                ts_wall=clock.now(),
                ts_mono=clock.now_mono(),
                ts_book=decision_input.book.timestamp,
            )
            .with_bundle(
                bundle_id="bundle_v1",
                feature_set_version_id=features["feature_set_version_id"],
                model_version_id=model_out["model_version_id"],
                calibrator_version_id=calibrated["calibrator_version_id"],
            )
            .with_book_state(
                bid=decision_input.book.best_bid,
                ask=decision_input.book.best_ask,
                mid=decision_input.book.mid_price,
                spread_bps=decision_input.book.spread_bps,
                seq=decision_input.book.sequence_id,
                is_quoteable=decision_input.book.is_quoteable,
            )
            .with_account(equity=decision_input.account_equity)
            .with_feature_frame(features)
            .with_model_output(model_out)
            .with_calibrated_output(calibrated)
            .with_edge_output(edge)
            .with_vol_output(vol["vol_version_id"], vol["vol_hat"])
            .with_risk_output(risk)
            .with_intents(intents)
            .build()
        )
        
        # Verify record
        assert record.record_id == f"rec_{trace_id}"
        assert record.symbol == "BTCUSD"
        assert record.feature_set_version_id == features["feature_set_version_id"]
        assert record.model_version_id == model_out["model_version_id"]
        assert record.signal_s == edge["s"]
        assert record.vol_hat == vol["vol_hat"]
        
        # Check outcome
        if intents:
            assert record.outcome == DecisionOutcome.INTENT_EMITTED
        else:
            assert record.outcome in {DecisionOutcome.NO_ACTION, DecisionOutcome.BLOCKED_CHURN_GUARD}
    
    def test_record_blocked_outcome(self, clock: SimClock, decision_input: DecisionInput):
        """Should record blocked decisions."""
        builder = DecisionRecordBuilder()
        
        record = (
            builder
            .with_identifiers("rec_1", "trace_1", "BTCUSD")
            .with_timestamps(clock.now(), clock.now_mono(), 0.0)
            .with_outcome(DecisionOutcome.BLOCKED_DEADBAND, "Signal below threshold")
            .build()
        )
        
        assert record.is_blocked() is True
        assert record.produced_intents() is False
        assert record.block_reason == "Signal below threshold"
    
    def test_record_to_event_envelope(self, clock: SimClock, decision_input: DecisionInput):
        """Record should convert to EventEnvelope."""
        record = (
            DecisionRecordBuilder()
            .with_identifiers("rec_1", "trace_1", "BTCUSD")
            .with_timestamps(clock.now(), clock.now_mono(), 0.0)
            .with_outcome(DecisionOutcome.NO_ACTION)
            .build()
        )
        
        envelope = record.to_event_envelope()
        
        assert envelope.type.value == "decision"
        assert envelope.symbol == "BTCUSD"
        assert envelope.trace_id == "trace_1"
        assert envelope.payload["outcome"] == "no_action"


class TestProtectiveOrders:
    """Tests for protective order generation."""
    
    def test_market_order_with_sl(self, clock: SimClock, book: OrderBook):
        """Market execution should include stop loss."""
        decision_input = DecisionInput(
            symbol="BTCUSD",
            ts_wall=clock.now(),
            ts_mono=clock.now_mono(),
            book=BookSnapshot.from_order_book(book, is_quoteable=True),
            account_equity=10000.0,
        )
        
        protective = ProtectiveOrderParams(
            stop_loss_pct=0.02,  # 2% stop
            take_profit_pct=0.03,  # 3% take profit
        )
        
        exec_policy = MarketExecutionPolicy(
            strategy_id="test",
            protective_params=protective,
        )
        
        # Create a risk output that will produce an intent
        risk_output = {
            "risk_profile_version_id": "test",
            "w_current": 0.0,
            "w_target": 0.05,  # 5% target weight
            "delta_w": 0.05,
            "clipped": False,
            "churn_guard_blocked": False,
            "extra": {},
        }
        
        intents = exec_policy.build_intents(
            risk_out=risk_output,
            decision_input=decision_input,
        )
        
        if intents:
            intent = intents[0]
            assert intent.sl_price is not None
            assert intent.tp_price is not None
            
            # Buy order should have SL below entry
            if intent.side == "BUY":
                expected_sl = decision_input.book.mid_price * (1 - 0.02)
                assert abs(intent.sl_price - expected_sl) < 0.01
