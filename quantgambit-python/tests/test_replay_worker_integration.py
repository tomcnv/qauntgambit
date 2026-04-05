"""Integration tests for ReplayWorker."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.backtesting.replay_worker import ReplayWorker, ReplayConfig


class TestReplayWorkerIntegration:
    """Integration tests for ReplayWorker."""

    @pytest.fixture
    def sample_snapshots(self, tmp_path):
        """Create sample JSONL file with snapshots."""
        snapshots = [
            {
                "symbol": "BTC-USDT-SWAP",
                "timestamp": 1705000000,
                "market_context": {
                    "regime_label": "trending",
                    "session": "us",
                    "volatility_regime": "normal",
                },
                "features": {
                    "price": 42000.0,
                    "bid": 41999.0,
                    "ask": 42001.0,
                    "spread_bps": 0.5,
                    "bid_depth_usd": 100000.0,
                    "ask_depth_usd": 100000.0,
                    "confidence": 0.85,
                    "stop_loss": 41500.0,
                    "take_profit": 42500.0,
                    "volatility_regime": "normal",
                    "atr_5m": 50.0,
                    "timestamp": 1705000000,
                },
                "warmup_ready": True,
            },
            {
                "symbol": "BTC-USDT-SWAP",
                "timestamp": 1705000060,
                "market_context": {
                    "regime_label": "trending",
                    "session": "us",
                    "volatility_regime": "normal",
                },
                "features": {
                    "price": 42050.0,
                    "bid": 42049.0,
                    "ask": 42051.0,
                    "spread_bps": 0.5,
                    "bid_depth_usd": 100000.0,
                    "ask_depth_usd": 100000.0,
                    "confidence": 0.82,
                    "stop_loss": 41550.0,
                    "take_profit": 42550.0,
                    "volatility_regime": "normal",
                    "atr_5m": 48.0,
                    "timestamp": 1705000060,
                },
                "warmup_ready": True,
            },
        ]
        
        path = tmp_path / "snapshots.jsonl"
        with path.open("w") as f:
            for snapshot in snapshots:
                f.write(json.dumps(snapshot) + "\n")
        return path

    @pytest.mark.asyncio
    async def test_replay_processes_all_snapshots(self, sample_snapshots):
        """Test that ReplayWorker processes all snapshots."""
        # Create a mock decision engine that always rejects
        mock_engine = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.rejection_reason = "test_rejection"
        mock_ctx.profile_id = None
        mock_ctx.signal = None
        mock_engine.decide_with_context = AsyncMock(return_value=(False, mock_ctx))
        
        config = ReplayConfig(input_path=sample_snapshots)
        worker = ReplayWorker(
            engine=mock_engine,
            config=config,
            simulate=False,
        )
        
        results = await worker.run()
        
        assert len(results) == 2
        assert all(r["decision"] == "rejected" for r in results)
        assert all(r["rejection_reason"] == "test_rejection" for r in results)

    @pytest.mark.asyncio
    async def test_replay_with_simulation(self, sample_snapshots):
        """Test ReplayWorker with execution simulation."""
        # Create a mock decision engine that accepts with a signal
        mock_engine = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.rejection_reason = None
        mock_ctx.profile_id = "test_profile"
        mock_ctx.signal = {
            "side": "long",
            "size": 0.1,
            "strategy_id": "test_strategy",
        }
        mock_engine.decide_with_context = AsyncMock(return_value=(True, mock_ctx))
        
        config = ReplayConfig(
            input_path=sample_snapshots,
            fee_bps=1.0,
            slippage_bps=0.5,
        )
        worker = ReplayWorker(
            engine=mock_engine,
            config=config,
            simulate=True,
            starting_equity=10000.0,
        )
        
        results = await worker.run()
        
        assert len(results) == 2
        assert all(r["decision"] == "accepted" for r in results)
        assert all(r["equity"] is not None for r in results)
        
        # Check report was generated
        report = worker.get_report()
        assert report is not None

    @pytest.mark.asyncio
    async def test_replay_warmup_skipping(self, tmp_path):
        """Test that warmup snapshots are skipped."""
        snapshots = [
            {"symbol": "BTC", "timestamp": 1, "market_context": {}, "features": {"price": 100, "bid": 99, "ask": 101, "bid_depth_usd": 10000, "ask_depth_usd": 10000, "timestamp": 1}, "warmup_ready": False},
            {"symbol": "BTC", "timestamp": 2, "market_context": {}, "features": {"price": 101, "bid": 100, "ask": 102, "bid_depth_usd": 10000, "ask_depth_usd": 10000, "timestamp": 2}, "warmup_ready": False},
            {"symbol": "BTC", "timestamp": 3, "market_context": {}, "features": {"price": 102, "bid": 101, "ask": 103, "bid_depth_usd": 10000, "ask_depth_usd": 10000, "timestamp": 3}, "warmup_ready": True},
        ]
        
        path = tmp_path / "warmup.jsonl"
        with path.open("w") as f:
            for s in snapshots:
                f.write(json.dumps(s) + "\n")
        
        mock_engine = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.rejection_reason = "test"
        mock_ctx.profile_id = None
        mock_ctx.signal = None
        mock_engine.decide_with_context = AsyncMock(return_value=(False, mock_ctx))
        
        config = ReplayConfig(
            input_path=path,
            warmup_min_snapshots=2,  # Skip first 2
        )
        worker = ReplayWorker(engine=mock_engine, config=config, simulate=False)
        
        results = await worker.run()
        
        # First 2 should be warmup, last 1 should be processed
        warmup_count = sum(1 for r in results if r["decision"] == "warmup")
        processed_count = sum(1 for r in results if r["decision"] != "warmup")
        
        assert warmup_count == 2
        assert processed_count == 1

    @pytest.mark.asyncio
    async def test_replay_equity_sampling(self, sample_snapshots):
        """Test equity curve sampling."""
        mock_engine = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.rejection_reason = "test"
        mock_ctx.profile_id = None
        mock_ctx.signal = None
        mock_engine.decide_with_context = AsyncMock(return_value=(False, mock_ctx))
        
        config = ReplayConfig(
            input_path=sample_snapshots,
            equity_sample_every=1,  # Sample every snapshot
        )
        worker = ReplayWorker(
            engine=mock_engine,
            config=config,
            simulate=True,
            starting_equity=10000.0,
        )
        
        results = await worker.run()
        
        # All results should have equity values
        assert all(r["equity"] is not None for r in results)
        # Starting equity should be preserved (no trades)
        assert all(r["equity"] == 10000.0 for r in results)


class TestReplayConfig:
    """Tests for ReplayConfig."""

    def test_default_values(self, tmp_path):
        """Test default configuration values."""
        config = ReplayConfig(input_path=tmp_path / "test.jsonl")
        
        assert config.sleep_ms == 0
        assert config.fee_bps == 1.0
        assert config.fee_model == "flat"
        assert config.slippage_bps == 0.0
        assert config.equity_sample_every == 1
        assert config.max_equity_points == 2000
        assert config.warmup_min_snapshots == 0

    def test_from_env(self, tmp_path, monkeypatch):
        """Test configuration from environment variables."""
        monkeypatch.setenv("BACKTEST_FEE_BPS", "2.5")
        monkeypatch.setenv("BACKTEST_SLIPPAGE_BPS", "1.0")
        monkeypatch.setenv("BACKTEST_WARMUP_SNAPSHOTS", "100")
        
        config = ReplayConfig.from_env(tmp_path / "test.jsonl")
        
        assert config.fee_bps == 2.5
        assert config.slippage_bps == 1.0
        assert config.warmup_min_snapshots == 100
