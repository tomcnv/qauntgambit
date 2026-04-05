"""Property-based tests for StageContextBuilder.

Feature: backtest-pipeline-unification, Property 4: StageContext Completeness

Tests that:
- All required fields are present in constructed StageContext
- Missing historical data is handled gracefully with safe defaults

Validates: Requirements 3.1, 3.2, 3.3, 3.4
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from dataclasses import dataclass

from quantgambit.backtesting.stage_context_builder import StageContextBuilder
from quantgambit.deeptrader_core.types import MarketSnapshot, Features, AccountState


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Generate realistic price values
price_strategy = st.floats(min_value=1000.0, max_value=200000.0, allow_nan=False, allow_infinity=False)

# Generate spread in basis points
spread_bps_strategy = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# Generate depth in USD
depth_strategy = st.floats(min_value=0.0, max_value=10000000.0, allow_nan=False, allow_infinity=False)

# Generate imbalance values (-1 to 1)
imbalance_strategy = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Generate trend direction
trend_direction_strategy = st.sampled_from(["up", "down", "flat"])

# Generate volatility regime
vol_regime_strategy = st.sampled_from(["low", "normal", "high", "extreme"])

# Generate position in value
position_in_value_strategy = st.sampled_from(["above", "below", "inside"])

# Generate symbol
symbol_strategy = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])


@st.composite
def market_snapshot_strategy(draw):
    """Generate a MarketSnapshot with random but valid values."""
    price = draw(price_strategy)
    spread_bps = draw(spread_bps_strategy)
    
    return MarketSnapshot(
        symbol=draw(symbol_strategy),
        exchange="bybit",
        timestamp_ns=int(draw(st.integers(min_value=1000000000000000000, max_value=2000000000000000000))),
        snapshot_age_ms=draw(st.floats(min_value=0, max_value=5000, allow_nan=False)),
        mid_price=price,
        bid=price * (1 - spread_bps / 20000),
        ask=price * (1 + spread_bps / 20000),
        spread_bps=spread_bps,
        bid_depth_usd=draw(depth_strategy),
        ask_depth_usd=draw(depth_strategy),
        depth_imbalance=draw(imbalance_strategy),
        imb_1s=draw(imbalance_strategy),
        imb_5s=draw(imbalance_strategy),
        imb_30s=draw(imbalance_strategy),
        orderflow_persistence_sec=0,
        rv_1s=0,
        rv_10s=0,
        rv_1m=0,
        vol_shock=draw(st.booleans()),
        vol_regime=draw(vol_regime_strategy),
        vol_regime_score=draw(st.floats(min_value=0, max_value=1, allow_nan=False)),
        trend_direction=draw(trend_direction_strategy),
        trend_strength=draw(st.floats(min_value=0, max_value=1, allow_nan=False)),
        poc_price=price * draw(st.floats(min_value=0.95, max_value=1.05, allow_nan=False)),
        vah_price=price * draw(st.floats(min_value=1.0, max_value=1.1, allow_nan=False)),
        val_price=price * draw(st.floats(min_value=0.9, max_value=1.0, allow_nan=False)),
        position_in_value=draw(position_in_value_strategy),
        expected_fill_slippage_bps=draw(st.floats(min_value=0, max_value=10, allow_nan=False)),
        typical_spread_bps=spread_bps,
        data_quality_score=draw(st.floats(min_value=0, max_value=1, allow_nan=False)),
        ws_connected=True,
    )


@st.composite
def features_strategy(draw):
    """Generate a Features object with random but valid values."""
    price = draw(price_strategy)
    poc = price * draw(st.floats(min_value=0.95, max_value=1.05, allow_nan=False))
    
    return Features(
        symbol=draw(symbol_strategy),
        price=price,
        spread=draw(st.floats(min_value=0, max_value=0.01, allow_nan=False)),
        rotation_factor=draw(st.floats(min_value=-10, max_value=10, allow_nan=False)),
        position_in_value=draw(position_in_value_strategy),
        timestamp=draw(st.floats(min_value=1000000000, max_value=2000000000, allow_nan=False)),
        distance_to_val=draw(st.floats(min_value=-1000, max_value=1000, allow_nan=False)),
        distance_to_vah=draw(st.floats(min_value=-1000, max_value=1000, allow_nan=False)),
        distance_to_poc=price - poc,
        value_area_low=poc * 0.98,
        value_area_high=poc * 1.02,
        point_of_control=poc,
        atr_5m=price * 0.005,
        atr_5m_baseline=price * 0.005,
        bid_depth_usd=draw(depth_strategy),
        ask_depth_usd=draw(depth_strategy),
        orderbook_imbalance=draw(imbalance_strategy),
        orderflow_imbalance=draw(imbalance_strategy),
    )


@st.composite
def account_state_strategy(draw):
    """Generate an AccountState with random but valid values."""
    equity = draw(st.floats(min_value=1000, max_value=1000000, allow_nan=False))
    
    return AccountState(
        equity=equity,
        daily_pnl=draw(st.floats(min_value=-equity * 0.1, max_value=equity * 0.1, allow_nan=False)),
        max_daily_loss=equity * 0.02,
        open_positions=draw(st.integers(min_value=0, max_value=5)),
        symbol_open_positions=draw(st.integers(min_value=0, max_value=3)),
        symbol_daily_pnl=draw(st.floats(min_value=-1000, max_value=1000, allow_nan=False)),
    )


# =============================================================================
# Property Tests
# =============================================================================

class TestStageContextBuilderFieldMappingProperties:
    """Property-based tests for StageContextBuilder field mapping.
    
    Feature: backtest-field-mapping-fix, Property 3: StageContextBuilder Field Completeness
    Feature: backtest-field-mapping-fix, Property 4: StageContextBuilder Market Context Fields
    
    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    
    @given(
        snapshot=market_snapshot_strategy(),
        features=features_strategy(),
        account=account_state_strategy(),
    )
    @settings(max_examples=100)
    def test_stage_context_builder_features_field_completeness(
        self,
        snapshot: MarketSnapshot,
        features: Features,
        account: AccountState,
    ):
        """Property 3: StageContextBuilder Field Completeness.
        
        Feature: backtest-field-mapping-fix, Property 3: StageContextBuilder Field Completeness
        
        *For any* MarketSnapshot with valid bid/ask prices, when StageContextBuilder
        builds a StageContext, the features dict SHALL contain `bid`, `ask`, `best_bid`,
        and `best_ask` fields, with `bid == best_bid` and `ask == best_ask`.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Ensure we have valid bid/ask prices
        assume(snapshot.bid is not None and snapshot.bid > 0)
        assume(snapshot.ask is not None and snapshot.ask > 0)
        
        builder = StageContextBuilder()
        ctx = builder.build(
            symbol=snapshot.symbol,
            snapshot=snapshot,
            features=features,
            account_state=account,
        )
        
        features_dict = ctx.data["features"]
        
        # Property: features dict SHALL contain bid, ask, best_bid, best_ask fields
        assert "bid" in features_dict, "features dict missing 'bid' field"
        assert "ask" in features_dict, "features dict missing 'ask' field"
        assert "best_bid" in features_dict, "features dict missing 'best_bid' field"
        assert "best_ask" in features_dict, "features dict missing 'best_ask' field"
        
        # Property: bid == best_bid and ask == best_ask
        assert features_dict["bid"] == features_dict["best_bid"], (
            f"bid ({features_dict['bid']}) != best_bid ({features_dict['best_bid']})"
        )
        assert features_dict["ask"] == features_dict["best_ask"], (
            f"ask ({features_dict['ask']}) != best_ask ({features_dict['best_ask']})"
        )
        
        # Property: values should match snapshot's bid/ask
        assert features_dict["bid"] == snapshot.bid, (
            f"features bid ({features_dict['bid']}) != snapshot.bid ({snapshot.bid})"
        )
        assert features_dict["ask"] == snapshot.ask, (
            f"features ask ({features_dict['ask']}) != snapshot.ask ({snapshot.ask})"
        )
    
    @given(
        snapshot=market_snapshot_strategy(),
        features=features_strategy(),
        account=account_state_strategy(),
    )
    @settings(max_examples=100)
    def test_stage_context_builder_market_context_fields(
        self,
        snapshot: MarketSnapshot,
        features: Features,
        account: AccountState,
    ):
        """Property 4: StageContextBuilder Market Context Fields.
        
        Feature: backtest-field-mapping-fix, Property 4: StageContextBuilder Market Context Fields
        
        *For any* MarketSnapshot with valid bid/ask prices, when StageContextBuilder
        builds a StageContext, the market_context dict SHALL contain `best_bid` and
        `best_ask` fields matching the snapshot's bid and ask values.
        
        **Validates: Requirements 2.2**
        """
        # Ensure we have valid bid/ask prices
        assume(snapshot.bid is not None and snapshot.bid > 0)
        assume(snapshot.ask is not None and snapshot.ask > 0)
        
        builder = StageContextBuilder()
        ctx = builder.build(
            symbol=snapshot.symbol,
            snapshot=snapshot,
            features=features,
            account_state=account,
        )
        
        market_context = ctx.data["market_context"]
        
        # Property: market_context dict SHALL contain best_bid and best_ask fields
        assert "best_bid" in market_context, "market_context missing 'best_bid' field"
        assert "best_ask" in market_context, "market_context missing 'best_ask' field"
        
        # Property: best_bid and best_ask SHALL match snapshot's bid and ask values
        assert market_context["best_bid"] == snapshot.bid, (
            f"market_context best_bid ({market_context['best_bid']}) != snapshot.bid ({snapshot.bid})"
        )
        assert market_context["best_ask"] == snapshot.ask, (
            f"market_context best_ask ({market_context['best_ask']}) != snapshot.ask ({snapshot.ask})"
        )


class TestStageContextBuilderProperties:
    """Property-based tests for StageContextBuilder.
    
    Feature: backtest-pipeline-unification, Property 4: StageContext Completeness
    """
    
    @given(
        snapshot=market_snapshot_strategy(),
        features=features_strategy(),
        account=account_state_strategy(),
    )
    @settings(max_examples=100)
    def test_all_required_fields_present(
        self,
        snapshot: MarketSnapshot,
        features: Features,
        account: AccountState,
    ):
        """Property: All required fields are present in StageContext.
        
        For any valid input, the constructed StageContext SHALL contain
        all required fields: symbol, features, market_context, account, positions.
        
        Validates: Requirements 3.1
        """
        builder = StageContextBuilder()
        ctx = builder.build(
            symbol=snapshot.symbol,
            snapshot=snapshot,
            features=features,
            account_state=account,
        )
        
        # Validate using builder's validation method
        errors = builder.validate_context(ctx)
        
        assert len(errors) == 0, f"Missing required fields: {errors}"
    
    @given(
        snapshot=market_snapshot_strategy(),
        features=features_strategy(),
        account=account_state_strategy(),
        ema_fast=st.one_of(st.none(), price_strategy),
        ema_slow=st.one_of(st.none(), price_strategy),
    )
    @settings(max_examples=100)
    def test_trend_indicators_in_features(
        self,
        snapshot: MarketSnapshot,
        features: Features,
        account: AccountState,
        ema_fast,
        ema_slow,
    ):
        """Property: Trend indicators are included in features.
        
        For any input, the features dict SHALL include ema_fast_15m and ema_slow_15m.
        
        Validates: Requirements 3.2
        """
        builder = StageContextBuilder()
        ctx = builder.build(
            symbol=snapshot.symbol,
            snapshot=snapshot,
            features=features,
            account_state=account,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
        )
        
        features_dict = ctx.data["features"]
        
        # EMA fields should be present (may be None if not provided)
        assert "ema_fast_15m" in features_dict, "ema_fast_15m missing from features"
        assert "ema_slow_15m" in features_dict, "ema_slow_15m missing from features"
        
        # If provided, values should match
        if ema_fast is not None:
            assert features_dict["ema_fast_15m"] == ema_fast
        if ema_slow is not None:
            assert features_dict["ema_slow_15m"] == ema_slow
    
    @given(
        snapshot=market_snapshot_strategy(),
        features=features_strategy(),
        account=account_state_strategy(),
    )
    @settings(max_examples=100)
    def test_market_context_has_trend_fields(
        self,
        snapshot: MarketSnapshot,
        features: Features,
        account: AccountState,
    ):
        """Property: Market context includes trend_direction, trend_strength, volatility_regime.
        
        For any input, the market_context dict SHALL include all required trend fields.
        
        Validates: Requirements 3.3
        """
        builder = StageContextBuilder()
        ctx = builder.build(
            symbol=snapshot.symbol,
            snapshot=snapshot,
            features=features,
            account_state=account,
        )
        
        market_context = ctx.data["market_context"]
        
        assert "trend_direction" in market_context, "trend_direction missing"
        assert "trend_strength" in market_context, "trend_strength missing"
        assert "volatility_regime" in market_context, "volatility_regime missing"
        
        # Values should be valid
        assert market_context["trend_direction"] in ["up", "down", "flat"]
        assert 0 <= market_context["trend_strength"] <= 1
        assert market_context["volatility_regime"] in ["low", "normal", "high", "extreme"]
    
    @given(
        snapshot=market_snapshot_strategy(),
        features=features_strategy(),
        account=account_state_strategy(),
    )
    @settings(max_examples=100)
    def test_positions_is_list(
        self,
        snapshot: MarketSnapshot,
        features: Features,
        account: AccountState,
    ):
        """Property: Positions is always a list.
        
        For any input, positions SHALL be a list (possibly empty).
        """
        builder = StageContextBuilder()
        ctx = builder.build(
            symbol=snapshot.symbol,
            snapshot=snapshot,
            features=features,
            account_state=account,
        )
        
        assert isinstance(ctx.data["positions"], list)
    
    @given(
        snapshot=market_snapshot_strategy(),
        features=features_strategy(),
        account=account_state_strategy(),
    )
    @settings(max_examples=100)
    def test_symbol_matches(
        self,
        snapshot: MarketSnapshot,
        features: Features,
        account: AccountState,
    ):
        """Property: Symbol in context matches input symbol.
        
        For any input, the context symbol SHALL match the provided symbol.
        """
        builder = StageContextBuilder()
        ctx = builder.build(
            symbol=snapshot.symbol,
            snapshot=snapshot,
            features=features,
            account_state=account,
        )
        
        assert ctx.symbol == snapshot.symbol
        assert ctx.data["features"]["symbol"] == snapshot.symbol


# =============================================================================
# Unit Tests for Edge Cases
# =============================================================================

class TestStageContextBuilderEdgeCases:
    """Unit tests for edge cases and specific scenarios."""
    
    def test_handles_none_trend_direction(self):
        """Should handle None trend_direction with safe default."""
        builder = StageContextBuilder()
        
        # Create snapshot with None trend_direction
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            exchange="bybit",
            timestamp_ns=1000000000000000000,
            snapshot_age_ms=0,
            mid_price=50000.0,
            bid=49990.0,
            ask=50010.0,
            spread_bps=4.0,
            bid_depth_usd=100000,
            ask_depth_usd=100000,
            depth_imbalance=0,
            imb_1s=0,
            imb_5s=0,
            imb_30s=0,
            orderflow_persistence_sec=0,
            rv_1s=0,
            rv_10s=0,
            rv_1m=0,
            vol_shock=False,
            vol_regime="normal",
            vol_regime_score=0.5,
            trend_direction=None,  # None!
            trend_strength=None,  # None!
            poc_price=50000,
            vah_price=51000,
            val_price=49000,
            position_in_value="inside",
            expected_fill_slippage_bps=2,
            typical_spread_bps=4,
            data_quality_score=1.0,
            ws_connected=True,
        )
        
        features = Features(
            symbol="BTCUSDT",
            price=50000.0,
            spread=0.0004,
            rotation_factor=0,
            position_in_value="inside",
            timestamp=1000000000,
            distance_to_val=1000,
            distance_to_vah=-1000,
            distance_to_poc=0,
            value_area_low=49000,
            value_area_high=51000,
            point_of_control=50000,
            atr_5m=250,
            atr_5m_baseline=250,
            bid_depth_usd=100000,
            ask_depth_usd=100000,
            orderbook_imbalance=0,
            orderflow_imbalance=0,
        )
        
        account = AccountState(
            equity=10000,
            daily_pnl=0,
            max_daily_loss=200,
            open_positions=0,
            symbol_open_positions=0,
            symbol_daily_pnl=0,
        )
        
        ctx = builder.build(
            symbol="BTCUSDT",
            snapshot=snapshot,
            features=features,
            account_state=account,
        )
        
        # Should use safe defaults
        assert ctx.data["market_context"]["trend_direction"] == "flat"
        assert ctx.data["market_context"]["trend_strength"] == 0.0
    
    def test_handles_empty_positions(self):
        """Should handle empty positions list."""
        builder = StageContextBuilder()
        
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            exchange="bybit",
            timestamp_ns=1000000000000000000,
            snapshot_age_ms=0,
            mid_price=50000.0,
            bid=49990.0,
            ask=50010.0,
            spread_bps=4.0,
            bid_depth_usd=100000,
            ask_depth_usd=100000,
            depth_imbalance=0,
            imb_1s=0,
            imb_5s=0,
            imb_30s=0,
            orderflow_persistence_sec=0,
            rv_1s=0,
            rv_10s=0,
            rv_1m=0,
            vol_shock=False,
            vol_regime="normal",
            vol_regime_score=0.5,
            trend_direction="flat",
            trend_strength=0,
            poc_price=50000,
            vah_price=51000,
            val_price=49000,
            position_in_value="inside",
            expected_fill_slippage_bps=2,
            typical_spread_bps=4,
            data_quality_score=1.0,
            ws_connected=True,
        )
        
        features = Features(
            symbol="BTCUSDT",
            price=50000.0,
            spread=0.0004,
            rotation_factor=0,
            position_in_value="inside",
            timestamp=1000000000,
            distance_to_val=1000,
            distance_to_vah=-1000,
            distance_to_poc=0,
            value_area_low=49000,
            value_area_high=51000,
            point_of_control=50000,
            atr_5m=250,
            atr_5m_baseline=250,
            bid_depth_usd=100000,
            ask_depth_usd=100000,
            orderbook_imbalance=0,
            orderflow_imbalance=0,
        )
        
        account = AccountState(
            equity=10000,
            daily_pnl=0,
            max_daily_loss=200,
            open_positions=0,
            symbol_open_positions=0,
            symbol_daily_pnl=0,
        )
        
        ctx = builder.build(
            symbol="BTCUSDT",
            snapshot=snapshot,
            features=features,
            account_state=account,
            positions=None,  # None positions
        )
        
        assert ctx.data["positions"] == []
    
    def test_validation_catches_missing_fields(self):
        """Validation should catch missing required fields."""
        builder = StageContextBuilder()
        
        # Create a context with missing fields
        from quantgambit.signals.pipeline import StageContext
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": {},  # Missing required fields
                "market_context": {},  # Missing required fields
                # Missing account and positions
            },
        )
        
        errors = builder.validate_context(ctx)
        
        assert len(errors) > 0
        assert any("features" in e for e in errors)
        assert any("market_context" in e for e in errors)
        assert any("account" in e for e in errors)
        assert any("positions" in e for e in errors)
