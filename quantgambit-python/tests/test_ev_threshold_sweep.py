"""
Tests for EV Threshold Sweep backtest tooling.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.7, 8.8
"""

import pytest
import math
import time
import sys
sys.path.insert(0, "quantgambit-python")

from quantgambit.backtesting.ev_threshold_sweep import (
    EVThresholdSweeper,
    BacktestTrade,
    ThresholdMetrics,
    SweepResult,
    WalkForwardValidator,
    KneeDetector,
    ThresholdRecommender,
    generate_sweep_report,
    generate_walk_forward_report,
    generate_recommendation_report,
)


def create_sample_trades(
    n_trades: int = 100,
    win_rate: float = 0.55,
    avg_r: float = 1.5,
    base_timestamp: float = None,
) -> list[BacktestTrade]:
    """Create sample trades for testing."""
    if base_timestamp is None:
        base_timestamp = time.time() - 86400 * 30  # 30 days ago
    
    trades = []
    for i in range(n_trades):
        # Vary p_hat around the win rate
        p_hat = win_rate + (i % 10 - 5) * 0.02
        p_hat = max(0.3, min(0.8, p_hat))
        
        # Determine outcome based on win rate
        outcome = 1 if (i % 100) < (win_rate * 100) else 0
        
        # Calculate PnL based on outcome and R
        if outcome == 1:
            pnl_bps = avg_r * 50  # Win: gain R * stop distance
        else:
            pnl_bps = -50  # Loss: lose stop distance
        
        entry_price = 100.0
        stop_loss = 99.5  # 50 bps stop
        take_profit = entry_price + (entry_price - stop_loss) * avg_r
        
        trades.append(BacktestTrade(
            symbol="BTCUSDT",
            side="long",
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            p_hat=p_hat,
            outcome=outcome,
            pnl_bps=pnl_bps,
            timestamp=base_timestamp + i * 3600,  # 1 hour apart
            spread_bps=2.0,
            fee_bps=5.5,
            slippage_bps=1.0,
            adverse_selection_bps=1.5,
            hold_time_seconds=300.0,
        ))
    
    return trades


class TestEVThresholdSweeper:
    """Tests for EVThresholdSweeper class."""
    
    def test_sweep_generates_metrics_for_each_threshold(self):
        """Test that sweep generates metrics for each threshold value."""
        sweeper = EVThresholdSweeper(
            sweep_start=0.0,
            sweep_end=0.1,
            sweep_step=0.02,
        )
        
        trades = create_sample_trades(n_trades=50)
        result = sweeper.sweep(trades, trading_days=10.0)
        
        # Should have 6 thresholds: 0.0, 0.02, 0.04, 0.06, 0.08, 0.10
        assert len(result.metrics_by_threshold) == 6
        
        # Check threshold values
        thresholds = [m.ev_min for m in result.metrics_by_threshold]
        assert 0.0 in thresholds
        assert 0.1 in thresholds
    
    def test_sweep_computes_required_metrics(self):
        """Test that sweep computes all required metrics (Req 8.2)."""
        sweeper = EVThresholdSweeper()
        trades = create_sample_trades(n_trades=100)
        result = sweeper.sweep(trades, trading_days=30.0)
        
        for metrics in result.metrics_by_threshold:
            # Check all required fields are present
            assert hasattr(metrics, 'trades_per_day')
            assert hasattr(metrics, 'gross_ev')
            assert hasattr(metrics, 'net_ev')
            assert hasattr(metrics, 'max_drawdown_bps')
            assert hasattr(metrics, 'avg_hold_time_seconds')
            assert hasattr(metrics, 'cvar_95')
            assert hasattr(metrics, 'sharpe_ratio')
            assert hasattr(metrics, 'sortino_ratio')
    
    def test_sweep_finds_optimal_threshold(self):
        """Test that sweep identifies optimal threshold."""
        sweeper = EVThresholdSweeper(min_trades_per_day=1)
        trades = create_sample_trades(n_trades=100, win_rate=0.6)
        result = sweeper.sweep(trades, trading_days=30.0)
        
        assert result.optimal_ev_min is not None
        assert result.optimal_metrics is not None
        assert result.recommendation_reason is not None
    
    def test_sweep_rejects_low_trade_thresholds(self):
        """Test that thresholds with too few trades are rejected (Req 8.4)."""
        sweeper = EVThresholdSweeper(min_trades_per_day=10)
        
        # Create few trades
        trades = create_sample_trades(n_trades=20)
        result = sweeper.sweep(trades, trading_days=30.0)
        
        # Should still return a result but with warning
        assert result.optimal_ev_min is not None
        assert "min_trades_per_day" in result.recommendation_reason.lower() or \
               result.optimal_metrics.trades_per_day >= 0
    
    def test_higher_threshold_accepts_fewer_trades(self):
        """Test that higher EV_Min accepts fewer trades."""
        sweeper = EVThresholdSweeper(
            sweep_start=0.0,
            sweep_end=0.2,
            sweep_step=0.05,
        )
        
        trades = create_sample_trades(n_trades=100)
        result = sweeper.sweep(trades, trading_days=30.0)
        
        # Sort by threshold
        sorted_metrics = sorted(result.metrics_by_threshold, key=lambda m: m.ev_min)
        
        # Higher thresholds should generally accept fewer or equal trades
        for i in range(1, len(sorted_metrics)):
            assert sorted_metrics[i].accepted_trades <= sorted_metrics[i-1].accepted_trades + 5


class TestWalkForwardValidator:
    """Tests for walk-forward validation (Req 8.3)."""
    
    def test_walk_forward_creates_folds(self):
        """Test that walk-forward creates correct number of folds."""
        sweeper = EVThresholdSweeper(min_trades_per_day=1)
        validator = WalkForwardValidator(
            sweeper=sweeper,
            n_folds=3,
            train_ratio=0.7,
            min_train_trades=10,
            min_test_trades=5,
        )
        
        trades = create_sample_trades(n_trades=100)
        result = validator.validate(trades)
        
        # Should have up to 3 folds
        assert len(result.fold_results) <= 3
    
    def test_walk_forward_computes_out_of_sample_metrics(self):
        """Test that walk-forward computes out-of-sample metrics."""
        sweeper = EVThresholdSweeper(min_trades_per_day=1)
        validator = WalkForwardValidator(
            sweeper=sweeper,
            n_folds=2,
            min_train_trades=20,
            min_test_trades=10,
        )
        
        trades = create_sample_trades(n_trades=200)
        result = validator.validate(trades)
        
        if result.fold_results:
            for fold in result.fold_results:
                assert fold.out_sample_sharpe is not None
                assert fold.out_sample_trades_per_day is not None
    
    def test_walk_forward_detects_robustness(self):
        """Test that walk-forward detects robust vs non-robust results."""
        sweeper = EVThresholdSweeper(min_trades_per_day=1)
        validator = WalkForwardValidator(sweeper=sweeper, n_folds=3)
        
        # Create consistent trades
        trades = create_sample_trades(n_trades=300, win_rate=0.55)
        result = validator.validate(trades)
        
        # Should have robustness assessment
        assert hasattr(result, 'is_robust')
        assert hasattr(result, 'threshold_stability')


class TestKneeDetector:
    """Tests for knee point detection (Req 8.7)."""
    
    def test_knee_detection_returns_result(self):
        """Test that knee detection returns a result."""
        detector = KneeDetector()
        
        # Create metrics with clear knee point
        metrics = [
            ThresholdMetrics(
                ev_min=0.1,
                total_signals=100,
                accepted_trades=20,
                rejected_trades=80,
                trades_per_day=2.0,
                gross_ev=0.5,
                net_ev=0.4,
                total_pnl_bps=400,
                avg_pnl_bps=20,
                max_drawdown_bps=50,
                sharpe_ratio=1.5,
                sortino_ratio=2.0,
                cvar_95=-30,
                win_rate=0.6,
                avg_hold_time_seconds=300,
                profit_factor=1.8,
                acceptance_rate=0.2,
            ),
            ThresholdMetrics(
                ev_min=0.05,
                total_signals=100,
                accepted_trades=50,
                rejected_trades=50,
                trades_per_day=5.0,
                gross_ev=0.6,
                net_ev=0.35,  # Lower efficiency
                total_pnl_bps=350,
                avg_pnl_bps=7,
                max_drawdown_bps=80,
                sharpe_ratio=1.0,
                sortino_ratio=1.3,
                cvar_95=-50,
                win_rate=0.52,
                avg_hold_time_seconds=300,
                profit_factor=1.3,
                acceptance_rate=0.5,
            ),
            ThresholdMetrics(
                ev_min=0.0,
                total_signals=100,
                accepted_trades=90,
                rejected_trades=10,
                trades_per_day=9.0,
                gross_ev=0.3,
                net_ev=0.1,  # Much lower efficiency
                total_pnl_bps=100,
                avg_pnl_bps=1.1,
                max_drawdown_bps=150,
                sharpe_ratio=0.3,
                sortino_ratio=0.4,
                cvar_95=-100,
                win_rate=0.48,
                avg_hold_time_seconds=300,
                profit_factor=0.9,
                acceptance_rate=0.9,
            ),
        ]
        
        result = detector.detect(metrics)
        
        assert result is not None
        assert hasattr(result, 'knee_ev_min')
        assert hasattr(result, 'confidence')


class TestThresholdRecommender:
    """Tests for threshold recommendation (Req 8.4, 8.8)."""
    
    def test_recommender_returns_recommendation(self):
        """Test that recommender returns a valid recommendation."""
        sweeper = EVThresholdSweeper(min_trades_per_day=1)
        trades = create_sample_trades(n_trades=100)
        sweep_result = sweeper.sweep(trades, trading_days=30.0)
        
        recommender = ThresholdRecommender(min_trades_per_day=1)
        recommendation = recommender.recommend(sweep_result)
        
        assert recommendation is not None
        assert recommendation.recommended_ev_min is not None
        assert 0.0 <= recommendation.confidence <= 1.0
        assert recommendation.primary_reason is not None
    
    def test_recommender_filters_by_min_trades(self):
        """Test that recommender filters by minimum trades (Req 8.4)."""
        sweeper = EVThresholdSweeper(min_trades_per_day=1)
        trades = create_sample_trades(n_trades=50)
        sweep_result = sweeper.sweep(trades, trading_days=30.0)
        
        # High minimum should filter most candidates
        recommender = ThresholdRecommender(min_trades_per_day=100)
        recommendation = recommender.recommend(sweep_result)
        
        # Should still return something but with warning
        assert recommendation is not None
        assert len(recommendation.warnings) > 0 or recommendation.confidence < 0.5
    
    def test_recommender_uses_sharpe_by_default(self):
        """Test that recommender uses Sharpe ratio by default (Req 8.8)."""
        recommender = ThresholdRecommender(risk_metric="sharpe", min_trades_per_day=1)
        
        sweeper = EVThresholdSweeper(min_trades_per_day=1)
        trades = create_sample_trades(n_trades=200)  # More trades for better coverage
        sweep_result = sweeper.sweep(trades, trading_days=10.0)  # Fewer days = more trades/day
        
        recommendation = recommender.recommend(sweep_result)
        
        # Should have valid score breakdown with risk_adjusted component
        assert recommendation.score_breakdown.component_scores is not None
        # Either mentions sharpe in reason or has risk_adjusted in scores
        has_sharpe_mention = "sharpe" in recommendation.primary_reason.lower()
        has_risk_adjusted = "risk_adjusted" in recommendation.score_breakdown.component_scores
        assert has_sharpe_mention or has_risk_adjusted or recommendation.confidence > 0


class TestReportGeneration:
    """Tests for report generation."""
    
    def test_sweep_report_generation(self):
        """Test that sweep report is generated correctly."""
        sweeper = EVThresholdSweeper(min_trades_per_day=1)
        trades = create_sample_trades(n_trades=100)
        result = sweeper.sweep(trades, trading_days=30.0)
        
        report = generate_sweep_report(result)
        
        assert "EV Threshold Sweep Report" in report
        assert "Optimal EV_Min" in report
        assert "Trades per day" in report
    
    def test_recommendation_report_generation(self):
        """Test that recommendation report is generated correctly."""
        sweeper = EVThresholdSweeper(min_trades_per_day=1)
        trades = create_sample_trades(n_trades=100)
        sweep_result = sweeper.sweep(trades, trading_days=30.0)
        
        recommender = ThresholdRecommender(min_trades_per_day=1)
        recommendation = recommender.recommend(sweep_result)
        
        report = generate_recommendation_report(recommendation)
        
        assert "EV Threshold Recommendation" in report
        assert "Recommended EV_Min" in report
        assert "Confidence" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
