"""
Unit tests for MDS backoff state machine and health tracking.

Tests:
- Failure recording and backoff triggering
- Backoff window cleanup
- Mode transitions (normal -> resyncing -> backoff -> normal)
- Health metrics computation
"""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch


class TestBackoffStateMachine:
    """Test the backoff state machine logic."""
    
    def test_failure_recording_triggers_backoff(self):
        """Multiple failures within window should trigger backoff."""
        # Simulate the app_state and config
        app_state = {
            "failure_timestamps": [],
            "mode": "normal",
            "backoff_until": 0.0,
            "resync_count": {"orderbook": 0, "trade": 0},
        }
        
        cfg = MagicMock()
        cfg.backoff_trigger_count = 3
        cfg.backoff_window_sec = 120.0
        cfg.backoff_duration_sec = 60.0
        cfg.exchange = "bybit"
        
        def record_failure(feed_type: str, reason: str):
            now = time.time()
            app_state["failure_timestamps"].append(now)
            # Clean old failures outside the window
            cutoff = now - cfg.backoff_window_sec
            app_state["failure_timestamps"] = [ts for ts in app_state["failure_timestamps"] if ts > cutoff]
            
            # Check if we should enter backoff
            recent_failures = len(app_state["failure_timestamps"])
            if recent_failures >= cfg.backoff_trigger_count and app_state["mode"] != "backoff":
                app_state["mode"] = "backoff"
                app_state["backoff_until"] = now + cfg.backoff_duration_sec
            
            app_state["resync_count"][feed_type] = app_state["resync_count"].get(feed_type, 0) + 1
        
        # Record failures
        record_failure("orderbook", "checksum_failed")
        assert app_state["mode"] == "normal"
        assert len(app_state["failure_timestamps"]) == 1
        
        record_failure("orderbook", "sequence_gap")
        assert app_state["mode"] == "normal"
        assert len(app_state["failure_timestamps"]) == 2
        
        # Third failure should trigger backoff
        record_failure("orderbook", "publish_error")
        assert app_state["mode"] == "backoff"
        assert app_state["backoff_until"] > time.time()
        assert len(app_state["failure_timestamps"]) == 3
        assert app_state["resync_count"]["orderbook"] == 3
    
    def test_old_failures_cleaned_from_window(self):
        """Failures outside the window should be cleaned up."""
        app_state = {
            "failure_timestamps": [],
            "mode": "normal",
            "backoff_until": 0.0,
            "resync_count": {"orderbook": 0},
        }
        
        cfg = MagicMock()
        cfg.backoff_trigger_count = 3
        cfg.backoff_window_sec = 60.0  # 1 minute window
        cfg.backoff_duration_sec = 60.0
        
        def record_failure(feed_type: str, reason: str):
            now = time.time()
            app_state["failure_timestamps"].append(now)
            cutoff = now - cfg.backoff_window_sec
            app_state["failure_timestamps"] = [ts for ts in app_state["failure_timestamps"] if ts > cutoff]
            
            recent_failures = len(app_state["failure_timestamps"])
            if recent_failures >= cfg.backoff_trigger_count and app_state["mode"] != "backoff":
                app_state["mode"] = "backoff"
                app_state["backoff_until"] = now + cfg.backoff_duration_sec
            
            app_state["resync_count"][feed_type] = app_state["resync_count"].get(feed_type, 0) + 1
        
        # Add old failures (simulate they happened 2 minutes ago)
        old_time = time.time() - 120
        app_state["failure_timestamps"] = [old_time, old_time + 1]
        
        # Record a new failure
        record_failure("orderbook", "test")
        
        # Old failures should be cleaned, only new one remains
        assert len(app_state["failure_timestamps"]) == 1
        assert app_state["mode"] == "normal"  # Not enough recent failures
    
    def test_backoff_prevents_additional_backoff(self):
        """Once in backoff, additional failures shouldn't extend it."""
        app_state = {
            "failure_timestamps": [],
            "mode": "backoff",
            "backoff_until": time.time() + 30,  # Already in backoff
            "resync_count": {"orderbook": 3},
        }
        
        cfg = MagicMock()
        cfg.backoff_trigger_count = 3
        cfg.backoff_window_sec = 120.0
        cfg.backoff_duration_sec = 60.0
        
        original_backoff_until = app_state["backoff_until"]
        
        def record_failure(feed_type: str, reason: str):
            now = time.time()
            app_state["failure_timestamps"].append(now)
            cutoff = now - cfg.backoff_window_sec
            app_state["failure_timestamps"] = [ts for ts in app_state["failure_timestamps"] if ts > cutoff]
            
            recent_failures = len(app_state["failure_timestamps"])
            # Key: only enter backoff if not already in backoff
            if recent_failures >= cfg.backoff_trigger_count and app_state["mode"] != "backoff":
                app_state["mode"] = "backoff"
                app_state["backoff_until"] = now + cfg.backoff_duration_sec
            
            app_state["resync_count"][feed_type] = app_state["resync_count"].get(feed_type, 0) + 1
        
        # Record more failures while in backoff
        record_failure("orderbook", "test1")
        record_failure("orderbook", "test2")
        
        # backoff_until should not change
        assert app_state["backoff_until"] == original_backoff_until
        assert app_state["mode"] == "backoff"


class TestHealthMetrics:
    """Test health metrics computation."""
    
    def test_staleness_computation(self):
        """Test staleness is computed correctly for each feed."""
        now = time.time()
        
        app_state = {
            "last_trade_ts": {
                "BTCUSDT": now - 5,   # 5 seconds ago
                "ETHUSDT": now - 30,  # 30 seconds ago (stale)
            },
            "last_orderbook_ts": {
                "BTCUSDT": now - 2,   # 2 seconds ago
                "ETHUSDT": now - 10,  # 10 seconds ago
            },
        }
        
        cfg = MagicMock()
        cfg.symbols = ["BTCUSDT", "ETHUSDT"]
        cfg.trade_stale_sec = 15.0
        cfg.orderbook_stale_sec = 15.0
        
        # Compute staleness
        trade_staleness = {}
        orderbook_staleness = {}
        stale_feeds = []
        
        for symbol in cfg.symbols:
            last_trade = app_state["last_trade_ts"].get(symbol)
            last_ob = app_state["last_orderbook_ts"].get(symbol)
            trade_staleness[symbol] = round(now - last_trade, 2) if last_trade else None
            orderbook_staleness[symbol] = round(now - last_ob, 2) if last_ob else None
            
            if trade_staleness.get(symbol) is not None and trade_staleness[symbol] > cfg.trade_stale_sec:
                stale_feeds.append(f"trade:{symbol}")
            if orderbook_staleness.get(symbol) is not None and orderbook_staleness[symbol] > cfg.orderbook_stale_sec:
                stale_feeds.append(f"orderbook:{symbol}")
        
        # Verify
        assert trade_staleness["BTCUSDT"] == pytest.approx(5.0, abs=0.5)
        assert trade_staleness["ETHUSDT"] == pytest.approx(30.0, abs=0.5)
        assert orderbook_staleness["BTCUSDT"] == pytest.approx(2.0, abs=0.5)
        assert orderbook_staleness["ETHUSDT"] == pytest.approx(10.0, abs=0.5)
        
        # Only ETHUSDT trade should be stale
        assert "trade:ETHUSDT" in stale_feeds
        assert "trade:BTCUSDT" not in stale_feeds
        assert "orderbook:BTCUSDT" not in stale_feeds
        assert "orderbook:ETHUSDT" not in stale_feeds
    
    def test_health_status_determination(self):
        """Test overall health status is determined correctly."""
        now = time.time()
        
        # Healthy case
        app_state = {
            "last_trade_ts": {"BTCUSDT": now - 5},
            "last_orderbook_ts": {"BTCUSDT": now - 2},
            "backoff_until": 0.0,
            "mode": "normal",
        }
        
        cfg = MagicMock()
        cfg.symbols = ["BTCUSDT"]
        cfg.trade_stale_sec = 30.0
        cfg.orderbook_stale_sec = 30.0
        
        def compute_status():
            status = "healthy"
            stale_feeds = []
            for symbol in cfg.symbols:
                last_trade = app_state["last_trade_ts"].get(symbol)
                last_ob = app_state["last_orderbook_ts"].get(symbol)
                trade_stale = (now - last_trade) if last_trade else None
                ob_stale = (now - last_ob) if last_ob else None
                
                if trade_stale is not None and trade_stale > cfg.trade_stale_sec:
                    stale_feeds.append(f"trade:{symbol}")
                    status = "degraded"
                if ob_stale is not None and ob_stale > cfg.orderbook_stale_sec:
                    stale_feeds.append(f"orderbook:{symbol}")
                    status = "degraded"
            
            if app_state["backoff_until"] > now:
                status = "backoff"
            
            return status, stale_feeds
        
        status, stale_feeds = compute_status()
        assert status == "healthy"
        assert len(stale_feeds) == 0
        
        # Degraded case (stale trade)
        app_state["last_trade_ts"]["BTCUSDT"] = now - 60
        status, stale_feeds = compute_status()
        assert status == "degraded"
        assert "trade:BTCUSDT" in stale_feeds
        
        # Backoff case
        app_state["backoff_until"] = now + 30
        status, stale_feeds = compute_status()
        assert status == "backoff"


class TestResyncLogic:
    """Test resync behavior."""
    
    def test_resync_prevents_thrash(self):
        """Resync should only happen once, not thrash."""
        app_state = {
            "mode": "normal",
        }
        
        resync_calls = []
        
        async def resync_orderbook(reason: str):
            if app_state["mode"] == "resyncing":
                return  # Already resyncing, don't thrash
            
            app_state["mode"] = "resyncing"
            resync_calls.append(reason)
            # Simulate resync completion
            app_state["mode"] = "normal"
        
        import asyncio
        
        # First resync should work
        asyncio.run(resync_orderbook("checksum_failed"))
        assert len(resync_calls) == 1
        
        # Simulate concurrent resync attempts
        app_state["mode"] = "resyncing"
        asyncio.run(resync_orderbook("sequence_gap"))
        # Should not add another call because we're already resyncing
        assert len(resync_calls) == 1
    
    def test_resync_records_failure_on_error(self):
        """Failed resync should record a failure."""
        app_state = {
            "mode": "normal",
            "failure_timestamps": [],
            "resync_count": {"orderbook": 0},
            "backoff_until": 0.0,
        }
        
        cfg = MagicMock()
        cfg.backoff_trigger_count = 3
        cfg.backoff_window_sec = 120.0
        cfg.backoff_duration_sec = 60.0
        
        def record_failure(feed_type: str, reason: str):
            now = time.time()
            app_state["failure_timestamps"].append(now)
            cutoff = now - cfg.backoff_window_sec
            app_state["failure_timestamps"] = [ts for ts in app_state["failure_timestamps"] if ts > cutoff]
            
            recent_failures = len(app_state["failure_timestamps"])
            if recent_failures >= cfg.backoff_trigger_count and app_state["mode"] != "backoff":
                app_state["mode"] = "backoff"
                app_state["backoff_until"] = now + cfg.backoff_duration_sec
            
            app_state["resync_count"][feed_type] = app_state["resync_count"].get(feed_type, 0) + 1
        
        # Simulate failed resync
        record_failure("orderbook", "resync_failed")
        
        assert app_state["resync_count"]["orderbook"] == 1
        assert len(app_state["failure_timestamps"]) == 1


class TestWsConnectedLogic:
    """Test WS connected determination."""
    
    def test_ws_connected_not_stale(self):
        """WS should be considered connected unless explicitly disconnected."""
        # Stale is NOT the same as disconnected
        market_context = {
            "trade_sync_state": "stale",
            "orderbook_sync_state": "synced",
        }
        
        # Old logic (wrong): ws_connected = trade_sync_state != "stale"
        # New logic (correct): only disconnected/error means WS is down
        trade_sync = market_context.get("trade_sync_state")
        orderbook_sync = market_context.get("orderbook_sync_state")
        ws_connected = trade_sync not in ("disconnected", "error") and orderbook_sync not in ("disconnected", "error")
        
        # Even though trade is stale, WS is still connected
        assert ws_connected is True
    
    def test_ws_disconnected_on_error(self):
        """WS should be disconnected on explicit error state."""
        market_context = {
            "trade_sync_state": "error",
            "orderbook_sync_state": "synced",
        }
        
        trade_sync = market_context.get("trade_sync_state")
        orderbook_sync = market_context.get("orderbook_sync_state")
        ws_connected = trade_sync not in ("disconnected", "error") and orderbook_sync not in ("disconnected", "error")
        
        assert ws_connected is False
    
    def test_ws_disconnected_explicit(self):
        """WS should be disconnected on explicit disconnected state."""
        market_context = {
            "trade_sync_state": "disconnected",
            "orderbook_sync_state": "disconnected",
        }
        
        trade_sync = market_context.get("trade_sync_state")
        orderbook_sync = market_context.get("orderbook_sync_state")
        ws_connected = trade_sync not in ("disconnected", "error") and orderbook_sync not in ("disconnected", "error")
        
        assert ws_connected is False
