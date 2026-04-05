"""
Unit tests for CostDataQualityStage.

Tests that the stage correctly validates cost data freshness before EVGate.
"""

import pytest
import time
from dataclasses import dataclass
from quantgambit.signals.stages.cost_data_quality import (
    CostDataQualityStage,
    CostDataQualityConfig,
    CostDataQualityResult,
)
from quantgambit.signals.pipeline import StageContext, StageResult


@dataclass
class MockSignal:
    """Mock signal for testing."""
    side: str = "long"
    entry_price: float = 100.0
    stop_loss: float = 99.0
    take_profit: float = 102.0


class TestCostDataQualityConfig:
    """Tests for CostDataQualityConfig validation."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = CostDataQualityConfig()
        assert config.max_spread_age_ms == 500
        assert config.max_book_age_ms == 500
        assert config.require_slippage_model is False
        assert config.enabled is True
    
    def test_custom_config(self):
        """Test custom configuration values."""
        config = CostDataQualityConfig(
            max_spread_age_ms=250,
            max_book_age_ms=300,
            require_slippage_model=True,
            enabled=True,
        )
        assert config.max_spread_age_ms == 250
        assert config.max_book_age_ms == 300
        assert config.require_slippage_model is True
    
    def test_invalid_spread_age(self):
        """Test that invalid max_spread_age_ms raises ValueError."""
        with pytest.raises(ValueError, match="max_spread_age_ms must be positive"):
            CostDataQualityConfig(max_spread_age_ms=0)
        
        with pytest.raises(ValueError, match="max_spread_age_ms must be positive"):
            CostDataQualityConfig(max_spread_age_ms=-100)
    
    def test_invalid_book_age(self):
        """Test that invalid max_book_age_ms raises ValueError."""
        with pytest.raises(ValueError, match="max_book_age_ms must be positive"):
            CostDataQualityConfig(max_book_age_ms=0)


class TestCostDataQualityStage:
    """Tests for CostDataQualityStage."""
    
    @pytest.fixture
    def stage(self):
        """Create a CostDataQualityStage with default config."""
        return CostDataQualityStage()
    
    @pytest.fixture
    def strict_stage(self):
        """Create a CostDataQualityStage with strict config."""
        config = CostDataQualityConfig(
            max_spread_age_ms=100,
            max_book_age_ms=100,
            require_slippage_model=True,
        )
        return CostDataQualityStage(config=config)
    
    def _make_context(
        self,
        signal=None,
        spread_age_ms: float = 0,
        book_age_ms: float = 0,
        has_spread: bool = True,
        has_bid_ask: bool = True,
        slippage_model_available: bool = False,
        use_new_field_names: bool = False,
    ) -> StageContext:
        """Create a StageContext with specified market data.
        
        Args:
            use_new_field_names: If True, use book_recv_ms instead of legacy field names.
        """
        current_time_ms = time.time() * 1000
        
        if use_new_field_names:
            # Use the new field names from feature_worker
            market_context = {
                "book_recv_ms": current_time_ms - book_age_ms,
                "book_cts_ms": current_time_ms - book_age_ms,
                "spread": 0.01 if has_spread else None,
                "best_bid": 99.95 if has_bid_ask else None,
                "best_ask": 100.05 if has_bid_ask else None,
                "slippage_model_available": slippage_model_available,
            }
        else:
            # Use legacy field names for backwards compatibility
            market_context = {
                "spread_timestamp_ms": current_time_ms - spread_age_ms,
                "book_timestamp_ms": current_time_ms - book_age_ms,
                "spread": 0.01 if has_spread else None,
                "best_bid": 99.95 if has_bid_ask else None,
                "best_ask": 100.05 if has_bid_ask else None,
                "slippage_model_available": slippage_model_available,
            }
        
        return StageContext(
            symbol="BTCUSDT",
            signal=signal or MockSignal(),
            data={
                "market_context": market_context,
                "features": {},
            },
        )
    
    @pytest.mark.asyncio
    async def test_passes_with_fresh_data(self, stage):
        """Test that stage passes with fresh data."""
        ctx = self._make_context(spread_age_ms=50, book_age_ms=50)
        result = await stage.run(ctx)
        assert result == StageResult.CONTINUE
        assert "cost_data_quality_result" in ctx.data
        assert ctx.data["cost_data_quality_result"].is_valid is True
    
    @pytest.mark.asyncio
    async def test_rejects_stale_spread(self, stage):
        """Test that stage rejects when spread data is stale."""
        ctx = self._make_context(spread_age_ms=600)  # > 500ms default
        result = await stage.run(ctx)
        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "cost_data_quality"
        assert "Spread data stale" in ctx.rejection_detail["reject_reason"]
    
    @pytest.mark.asyncio
    async def test_rejects_stale_book(self, stage):
        """Test that stage rejects when book data is stale."""
        ctx = self._make_context(book_age_ms=600)  # > 500ms default
        result = await stage.run(ctx)
        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "cost_data_quality"
        assert "Book data stale" in ctx.rejection_detail["reject_reason"]
    
    @pytest.mark.asyncio
    async def test_rejects_missing_slippage_model_when_required(self, strict_stage):
        """Test that stage rejects when slippage model is required but unavailable."""
        ctx = self._make_context(
            spread_age_ms=50,
            book_age_ms=50,
            slippage_model_available=False,
        )
        result = await strict_stage.run(ctx)
        assert result == StageResult.REJECT
        assert "Slippage model unavailable" in ctx.rejection_detail["reject_reason"]
    
    @pytest.mark.asyncio
    async def test_passes_with_slippage_model_when_required(self, strict_stage):
        """Test that stage passes when slippage model is available and required."""
        ctx = self._make_context(
            spread_age_ms=50,
            book_age_ms=50,
            slippage_model_available=True,
        )
        result = await strict_stage.run(ctx)
        assert result == StageResult.CONTINUE
    
    @pytest.mark.asyncio
    async def test_skips_exit_signals(self, stage):
        """Test that stage skips exit signals."""
        exit_signal = MockSignal(side="close_long")
        ctx = self._make_context(signal=exit_signal, spread_age_ms=1000)
        result = await stage.run(ctx)
        assert result == StageResult.CONTINUE
    
    @pytest.mark.asyncio
    async def test_skips_when_no_signal(self, stage):
        """Test that stage skips when no signal present."""
        ctx = StageContext(
            symbol="BTCUSDT",
            signal=None,
            data={"market_context": {}},
        )
        result = await stage.run(ctx)
        assert result == StageResult.CONTINUE
    
    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, stage):
        """Test that stage skips when disabled."""
        stage.config.enabled = False
        ctx = self._make_context(spread_age_ms=1000)  # Would normally reject
        result = await stage.run(ctx)
        assert result == StageResult.CONTINUE
    
    @pytest.mark.asyncio
    async def test_uses_book_lag_if_provided(self, stage):
        """Test that stage uses book_lag_ms if provided instead of calculating from timestamp."""
        current_time_ms = time.time() * 1000
        ctx = StageContext(
            symbol="BTCUSDT",
            signal=MockSignal(),
            data={
                "market_context": {
                    "spread_timestamp_ms": current_time_ms,
                    "book_lag_ms": 600,  # Explicitly stale
                    "spread": 0.01,
                    "best_bid": 99.95,
                    "best_ask": 100.05,
                },
                "features": {},
            },
        )
        result = await stage.run(ctx)
        assert result == StageResult.REJECT
        assert "Book data stale" in ctx.rejection_detail["reject_reason"]
    
    @pytest.mark.asyncio
    async def test_uses_new_field_names(self, stage):
        """Test that stage works with new field names (book_recv_ms, book_cts_ms)."""
        ctx = self._make_context(
            spread_age_ms=50,
            book_age_ms=50,
            use_new_field_names=True,
        )
        result = await stage.run(ctx)
        assert result == StageResult.CONTINUE
        assert ctx.data["cost_data_quality_result"].is_valid is True
    
    @pytest.mark.asyncio
    async def test_rejects_stale_book_with_new_field_names(self, stage):
        """Test that stage rejects stale book data using new field names.
        
        Note: With new field names, spread age is also calculated from book_recv_ms
        since spread freshness is tied to orderbook freshness.
        """
        ctx = self._make_context(
            book_age_ms=600,  # > 500ms default - will trigger spread stale first
            use_new_field_names=True,
        )
        result = await stage.run(ctx)
        assert result == StageResult.REJECT
        # Either spread or book stale is acceptable since they use the same timestamp
        assert "stale" in ctx.rejection_detail["reject_reason"].lower()
    
    @pytest.mark.asyncio
    async def test_uses_feed_staleness_dict(self, stage):
        """Test that stage uses feed_staleness dict when timestamps not available."""
        ctx = StageContext(
            symbol="BTCUSDT",
            signal=MockSignal(),
            data={
                "market_context": {
                    "feed_staleness": {
                        "orderbook": 0.6,  # 600ms in seconds - stale
                    },
                    "spread": 0.01,
                    "best_bid": 99.95,
                    "best_ask": 100.05,
                },
                "features": {},
            },
        )
        result = await stage.run(ctx)
        assert result == StageResult.REJECT
        assert "stale" in ctx.rejection_detail["reject_reason"].lower()


class TestCostDataQualityResult:
    """Tests for CostDataQualityResult dataclass."""
    
    def test_default_result(self):
        """Test default result values."""
        result = CostDataQualityResult(is_valid=True)
        assert result.is_valid is True
        assert result.reject_reason is None
        assert result.spread_age_ms == 0.0
        assert result.book_age_ms == 0.0
        assert result.slippage_model_available is False
    
    def test_invalid_result(self):
        """Test invalid result with reason."""
        result = CostDataQualityResult(
            is_valid=False,
            reject_reason="Spread data stale",
            spread_age_ms=600.0,
        )
        assert result.is_valid is False
        assert result.reject_reason == "Spread data stale"
        assert result.spread_age_ms == 600.0
