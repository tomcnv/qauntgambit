"""
Unit tests for Correlation Guard functionality.

Tests cover:
1. BTC blocked when ETH long exists (same direction, high correlation)
2. BTC short allowed when ETH long exists (hedge)
3. Unknown pairs allowed (assume uncorrelated)
4. Threshold configuration respected
5. Disabled guard allows all
6. Excluded symbols bypass check
7. Alert sent on block
8. Statistics tracking
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from quantgambit.core.risk.correlation_guard import (
    CorrelationGuard,
    CorrelationGuardConfig,
    CorrelationCheckResult,
    CORRELATION_MATRIX,
)


@pytest.fixture
def mock_alerts_client():
    """Create mock alerts client."""
    client = AsyncMock()
    client.send = AsyncMock(return_value=True)
    return client


@pytest.fixture
def default_guard():
    """Create default correlation guard."""
    return CorrelationGuard(
        config=CorrelationGuardConfig(max_correlation=0.70),
    )


@pytest.fixture
def guard_with_alerts(mock_alerts_client):
    """Create guard with alerts client."""
    return CorrelationGuard(
        config=CorrelationGuardConfig(max_correlation=0.70),
        alerts_client=mock_alerts_client,
        tenant_id="test_tenant",
        bot_id="test_bot",
    )


class TestCorrelationGuardBasics:
    """Basic correlation guard tests."""
    
    @pytest.mark.asyncio
    async def test_blocks_btc_when_eth_long_exists(self, default_guard):
        """BTC long blocked when ETH long exists (85% correlated)."""
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        result = await default_guard.check("BTCUSDT", "long", existing)
        
        assert result.allowed is False
        assert "85%" in result.reason
        assert result.blocking_symbol == "ETHUSDT"
        assert result.correlation == 0.85
    
    @pytest.mark.asyncio
    async def test_allows_btc_short_when_eth_long(self, default_guard):
        """BTC short allowed when ETH long exists (hedge)."""
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        result = await default_guard.check("BTCUSDT", "short", existing)
        
        assert result.allowed is True
        assert result.reason is None
    
    @pytest.mark.asyncio
    async def test_blocks_eth_when_btc_long_exists(self, default_guard):
        """ETH long blocked when BTC long exists (reverse lookup)."""
        existing = [{"symbol": "BTCUSDT", "size": 0.5}]
        
        result = await default_guard.check("ETHUSDT", "long", existing)
        
        assert result.allowed is False
        assert result.blocking_symbol == "BTCUSDT"
    
    @pytest.mark.asyncio
    async def test_allows_uncorrelated_symbols(self, default_guard):
        """Unknown pairs should be allowed (assume uncorrelated)."""
        existing = [{"symbol": "BTCUSDT", "size": 1.0}]
        
        # RANDOMCOIN not in matrix
        result = await default_guard.check("RANDOMCOIN", "long", existing)
        
        assert result.allowed is True
    
    @pytest.mark.asyncio
    async def test_allows_same_symbol(self, default_guard):
        """Same symbol should not be blocked by correlation guard (handled elsewhere)."""
        existing = [{"symbol": "BTCUSDT", "size": 1.0}]
        
        result = await default_guard.check("BTCUSDT", "long", existing)
        
        assert result.allowed is True
        assert result.reason is None
    
    @pytest.mark.asyncio
    async def test_skips_zero_positions(self, default_guard):
        """Positions with zero size should be skipped."""
        existing = [
            {"symbol": "ETHUSDT", "size": 0.0},  # Closed position
            {"symbol": "SOLUSDT", "size": 1.0},
        ]
        
        # BTC/SOL is 75%, above 70% threshold
        result = await default_guard.check("BTCUSDT", "long", existing)
        
        assert result.allowed is False
        assert result.blocking_symbol == "SOLUSDT"


class TestCorrelationThreshold:
    """Tests for threshold configuration."""
    
    @pytest.mark.asyncio
    async def test_respects_high_threshold(self):
        """Should only block above configured threshold."""
        guard = CorrelationGuard(
            config=CorrelationGuardConfig(max_correlation=0.90),
        )
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        # BTC/ETH is 85%, below 90% threshold
        result = await guard.check("BTCUSDT", "long", existing)
        
        assert result.allowed is True
    
    @pytest.mark.asyncio
    async def test_respects_low_threshold(self):
        """Low threshold should block more pairs."""
        guard = CorrelationGuard(
            config=CorrelationGuardConfig(max_correlation=0.50),
        )
        existing = [{"symbol": "BTCUSDT", "size": 1.0}]
        
        # BTC/BNB is 70%, above 50% threshold
        result = await guard.check("BNBUSDT", "long", existing)
        
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_side_specific_thresholds_allow_shorts_but_block_longs(self):
        """Longs can remain strict while shorts are relaxed."""
        guard = CorrelationGuard(
            config=CorrelationGuardConfig(
                max_correlation=0.70,
                max_correlation_long=0.70,
                max_correlation_short=0.90,
            ),
        )
        existing = [{"symbol": "ETHUSDT", "size": -1.0}]  # existing short

        short_result = await guard.check("BTCUSDT", "short", existing)  # 85% corr
        long_result = await guard.check("BTCUSDT", "long", [{"symbol": "ETHUSDT", "size": 1.0}])

        assert short_result.allowed is True
        assert long_result.allowed is False


class TestGuardDisabled:
    """Tests for disabled guard."""
    
    @pytest.mark.asyncio
    async def test_disabled_allows_all(self):
        """Disabled guard should allow all."""
        guard = CorrelationGuard(
            config=CorrelationGuardConfig(enabled=False),
        )
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        result = await guard.check("BTCUSDT", "long", existing)
        
        assert result.allowed is True


class TestExcludedSymbols:
    """Tests for symbol exclusion."""
    
    @pytest.mark.asyncio
    async def test_excluded_new_symbol_bypasses_check(self):
        """Excluded new symbol should bypass check."""
        guard = CorrelationGuard(
            config=CorrelationGuardConfig(
                max_correlation=0.70,
                excluded_symbols={"BTCUSDT"},
            ),
        )
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        result = await guard.check("BTCUSDT", "long", existing)
        
        assert result.allowed is True
    
    @pytest.mark.asyncio
    async def test_excluded_existing_symbol_skipped(self):
        """Excluded existing symbol should be skipped."""
        guard = CorrelationGuard(
            config=CorrelationGuardConfig(
                max_correlation=0.70,
                excluded_symbols={"ETHUSDT"},
            ),
        )
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        result = await guard.check("BTCUSDT", "long", existing)
        
        assert result.allowed is True


class TestShortPositions:
    """Tests for short position handling."""
    
    @pytest.mark.asyncio
    async def test_blocks_short_when_short_exists(self, default_guard):
        """BTC short blocked when ETH short exists."""
        existing = [{"symbol": "ETHUSDT", "size": -1.0}]  # Short
        
        result = await default_guard.check("BTCUSDT", "short", existing)
        
        assert result.allowed is False
    
    @pytest.mark.asyncio
    async def test_allows_long_when_short_exists(self, default_guard):
        """BTC long allowed when ETH short exists (hedge)."""
        existing = [{"symbol": "ETHUSDT", "size": -1.0}]  # Short
        
        result = await default_guard.check("BTCUSDT", "long", existing)
        
        assert result.allowed is True


class TestAlerts:
    """Tests for alerting on blocks."""
    
    @pytest.mark.asyncio
    async def test_sends_alert_on_block(self, guard_with_alerts, mock_alerts_client):
        """Alert should be sent when position is blocked."""
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        await guard_with_alerts.check("BTCUSDT", "long", existing)
        
        mock_alerts_client.send.assert_called_once()
        call_args = mock_alerts_client.send.call_args
        
        assert call_args.kwargs["alert_type"] == "correlation_block"
        assert "BTCUSDT" in call_args.kwargs["message"]
        assert "ETHUSDT" in call_args.kwargs["message"]
        assert call_args.kwargs["metadata"]["correlation"] == 0.85
    
    @pytest.mark.asyncio
    async def test_no_alert_when_allowed(self, guard_with_alerts, mock_alerts_client):
        """No alert should be sent when position is allowed."""
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        await guard_with_alerts.check("RANDOMCOIN", "long", existing)
        
        mock_alerts_client.send.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_alert_failure_does_not_crash(self, guard_with_alerts, mock_alerts_client):
        """Alert failure should not crash the guard."""
        mock_alerts_client.send.side_effect = Exception("Webhook error")
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        # Should not raise
        result = await guard_with_alerts.check("BTCUSDT", "long", existing)
        
        assert result.allowed is False


class TestStatistics:
    """Tests for statistics tracking."""
    
    @pytest.mark.asyncio
    async def test_tracks_checks_and_blocks(self, default_guard):
        """Should track total checks and blocks."""
        existing_eth = [{"symbol": "ETHUSDT", "size": 1.0}]
        existing_none = []
        
        # 3 checks, 2 blocks
        await default_guard.check("BTCUSDT", "long", existing_eth)  # Block
        await default_guard.check("BTCUSDT", "short", existing_eth)  # Allow (hedge)
        await default_guard.check("BTCUSDT", "long", existing_none)  # Allow (no positions)
        
        stats = default_guard.get_stats()
        
        assert stats["checks_total"] == 3
        assert stats["blocks_total"] == 1
        assert stats["block_rate"] == pytest.approx(1/3)


class TestCorrelationMatrix:
    """Tests for correlation matrix."""
    
    def test_matrix_has_major_pairs(self):
        """Matrix should include major crypto pairs."""
        assert ("BTCUSDT", "ETHUSDT") in CORRELATION_MATRIX
        assert ("BTCUSDT", "SOLUSDT") in CORRELATION_MATRIX
        assert ("ETHUSDT", "SOLUSDT") in CORRELATION_MATRIX
    
    def test_correlations_are_valid(self):
        """All correlations should be between 0 and 1."""
        for pair, corr in CORRELATION_MATRIX.items():
            assert 0.0 <= corr <= 1.0, f"Invalid correlation for {pair}: {corr}"
    
    def test_get_correlation_both_orderings(self, default_guard):
        """get_correlation should work with both orderings."""
        # Matrix has (BTCUSDT, ETHUSDT)
        assert default_guard.get_correlation("BTCUSDT", "ETHUSDT") == 0.85
        assert default_guard.get_correlation("ETHUSDT", "BTCUSDT") == 0.85
    
    def test_get_correlation_same_symbol(self, default_guard):
        """Same symbol should return 1.0."""
        assert default_guard.get_correlation("BTCUSDT", "BTCUSDT") == 1.0
    
    def test_get_correlation_unknown_pair(self, default_guard):
        """Unknown pair should return 0.0."""
        assert default_guard.get_correlation("RANDOMCOIN", "OTHERCOIN") == 0.0
    
    def test_get_known_correlations(self, default_guard):
        """get_known_correlations should return flat dict."""
        known = default_guard.get_known_correlations()
        
        assert "BTCUSDT_ETHUSDT" in known
        assert known["BTCUSDT_ETHUSDT"] == 0.85


class TestUpdateCorrelation:
    """Tests for dynamic correlation updates."""
    
    def test_update_correlation(self, default_guard):
        """Should be able to update correlations."""
        # Initially unknown
        assert default_guard.get_correlation("NEWCOIN", "OTHERCOIN") == 0.0
        
        # Update
        default_guard.update_correlation("NEWCOIN", "OTHERCOIN", 0.75)
        
        # Now known
        assert default_guard.get_correlation("NEWCOIN", "OTHERCOIN") == 0.75
    
    def test_update_normalizes_order(self, default_guard):
        """Update should normalize symbol order."""
        # Update with one order
        default_guard.update_correlation("ZZZCOIN", "AAACOIN", 0.60)
        
        # Should work with both orders
        assert default_guard.get_correlation("AAACOIN", "ZZZCOIN") == 0.60
        assert default_guard.get_correlation("ZZZCOIN", "AAACOIN") == 0.60


class TestCaseInsensitivity:
    """Tests for case handling."""
    
    @pytest.mark.asyncio
    async def test_handles_lowercase_symbols(self, default_guard):
        """Should handle lowercase symbol names."""
        existing = [{"symbol": "ethusdt", "size": 1.0}]
        
        result = await default_guard.check("btcusdt", "long", existing)
        
        assert result.allowed is False
    
    @pytest.mark.asyncio
    async def test_handles_mixed_case_symbols(self, default_guard):
        """Should handle mixed case symbol names."""
        existing = [{"symbol": "EthUsdt", "size": 1.0}]
        
        result = await default_guard.check("BtcUsdt", "long", existing)
        
        assert result.allowed is False
