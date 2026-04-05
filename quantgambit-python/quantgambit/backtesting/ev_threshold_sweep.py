"""
EV Threshold Sweep - Backtest tool for finding optimal EV_Min threshold.

This module provides functionality to sweep EV_Min thresholds from 0 to 0.5
and compute metrics for each threshold to find the optimal balance between
trade frequency and profitability.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.7, 8.8
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Sequence
from enum import Enum

from quantgambit.signals.stages.ev_gate import (
    calculate_L_G_R,
    calculate_ev,
    calculate_p_min,
    calculate_cost_ratio,
    EVGateConfig,
    CostEstimator,
)


@dataclass
class BacktestTrade:
    """A single trade from historical data for backtesting."""
    symbol: str
    side: str  # "long" or "short"
    entry_price: float
    stop_loss: float
    take_profit: float
    p_hat: float  # Predicted win probability
    outcome: int  # 1 = win (hit TP), 0 = loss (hit SL)
    pnl_bps: float  # Actual PnL in basis points
    timestamp: float
    
    # Cost components
    spread_bps: float = 0.0
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    adverse_selection_bps: float = 1.5
    
    # Context
    regime_label: Optional[str] = None
    session: Optional[str] = None
    hold_time_seconds: float = 0.0


@dataclass
class ThresholdMetrics:
    """Metrics computed for a single EV_Min threshold.
    
    Requirements: 8.2
    """
    ev_min: float
    
    # Trade counts
    total_signals: int
    accepted_trades: int
    rejected_trades: int
    trades_per_day: float
    
    # PnL metrics
    gross_ev: float  # Sum of EV for accepted trades
    net_ev: float  # Sum of actual PnL for accepted trades
    total_pnl_bps: float
    avg_pnl_bps: float
    
    # Risk metrics
    max_drawdown_bps: float
    sharpe_ratio: float
    sortino_ratio: float
    cvar_95: float  # Conditional Value at Risk at 95%
    
    # Trade quality
    win_rate: float
    avg_hold_time_seconds: float
    profit_factor: float
    
    # Acceptance rate
    acceptance_rate: float


@dataclass
class SweepResult:
    """Result of a threshold sweep.
    
    Requirements: 8.1, 8.6, 8.7, 8.8
    """
    metrics_by_threshold: List[ThresholdMetrics]
    optimal_ev_min: float
    optimal_metrics: ThresholdMetrics
    knee_ev_min: Optional[float]  # Point where trades increase but net EV doesn't
    recommendation_reason: str
    
    # Walk-forward validation results (if performed)
    walk_forward_results: Optional[List["WalkForwardFold"]] = None


@dataclass
class WalkForwardFold:
    """Results from a single walk-forward validation fold.
    
    Requirements: 8.3
    """
    fold_index: int
    train_start: float
    train_end: float
    test_start: float
    test_end: float
    
    # In-sample metrics
    in_sample_optimal_ev_min: float
    in_sample_sharpe: float
    in_sample_trades_per_day: float
    
    # Out-of-sample metrics
    out_of_sample_sharpe: float
    out_of_sample_trades_per_day: float
    out_of_sample_net_ev: float


class EVThresholdSweeper:
    """
    Sweeps EV_Min thresholds to find optimal value.
    
    Requirements: 8.1, 8.2, 8.3, 8.4, 8.7, 8.8
    """
    
    def __init__(
        self,
        min_trades_per_day: int = 5,
        sweep_start: float = 0.0,
        sweep_end: float = 0.5,
        sweep_step: float = 0.01,
        cost_estimator: Optional[CostEstimator] = None,
        adverse_selection_bps: float = 1.5,
    ):
        """
        Initialize the threshold sweeper.
        
        Args:
            min_trades_per_day: Minimum trades per day to accept a threshold (Req 8.4)
            sweep_start: Starting EV_Min value (default 0.0)
            sweep_end: Ending EV_Min value (default 0.5)
            sweep_step: Step size for sweep (default 0.01)
            cost_estimator: Cost estimator for computing C
            adverse_selection_bps: Adverse selection buffer
        """
        self.min_trades_per_day = min_trades_per_day
        self.sweep_start = sweep_start
        self.sweep_end = sweep_end
        self.sweep_step = sweep_step
        self.cost_estimator = cost_estimator or CostEstimator()
        self.adverse_selection_bps = adverse_selection_bps
    
    def sweep(
        self,
        trades: List[BacktestTrade],
        trading_days: float,
    ) -> SweepResult:
        """
        Sweep EV_Min thresholds and compute metrics for each.
        
        Args:
            trades: List of historical trades with outcomes
            trading_days: Number of trading days in the dataset
            
        Returns:
            SweepResult with metrics for each threshold and recommendation
            
        Requirements: 8.1, 8.2
        """
        if not trades or trading_days <= 0:
            raise ValueError("Must provide trades and positive trading_days")
        
        # Generate threshold values
        thresholds = self._generate_thresholds()
        
        # Compute metrics for each threshold
        metrics_list = []
        for ev_min in thresholds:
            metrics = self._compute_metrics_for_threshold(trades, ev_min, trading_days)
            metrics_list.append(metrics)
        
        # Find optimal threshold
        optimal_ev_min, optimal_metrics, reason = self._find_optimal_threshold(metrics_list)
        
        # Find knee point
        knee_ev_min = self._find_knee_point(metrics_list)
        
        return SweepResult(
            metrics_by_threshold=metrics_list,
            optimal_ev_min=optimal_ev_min,
            optimal_metrics=optimal_metrics,
            knee_ev_min=knee_ev_min,
            recommendation_reason=reason,
        )
    
    def sweep_with_walk_forward(
        self,
        trades: List[BacktestTrade],
        n_folds: int = 5,
        train_ratio: float = 0.7,
    ) -> SweepResult:
        """
        Sweep thresholds using walk-forward validation.
        
        Args:
            trades: List of historical trades sorted by timestamp
            n_folds: Number of walk-forward folds
            train_ratio: Ratio of data to use for training in each fold
            
        Returns:
            SweepResult with walk-forward validation results
            
        Requirements: 8.3
        """
        if not trades:
            raise ValueError("Must provide trades")
        
        # Sort trades by timestamp
        sorted_trades = sorted(trades, key=lambda t: t.timestamp)
        
        # Create walk-forward folds
        folds = self._create_walk_forward_folds(sorted_trades, n_folds, train_ratio)
        
        walk_forward_results = []
        all_out_of_sample_sharpes = []
        
        for fold in folds:
            # Find optimal threshold on training data
            train_trades = [t for t in sorted_trades 
                          if fold.train_start <= t.timestamp < fold.train_end]
            test_trades = [t for t in sorted_trades 
                         if fold.test_start <= t.timestamp < fold.test_end]
            
            if not train_trades or not test_trades:
                continue
            
            # Compute trading days for each period
            train_days = (fold.train_end - fold.train_start) / 86400.0
            test_days = (fold.test_end - fold.test_start) / 86400.0
            
            # Sweep on training data
            train_result = self.sweep(train_trades, train_days)
            
            # Evaluate on test data
            test_metrics = self._compute_metrics_for_threshold(
                test_trades, 
                train_result.optimal_ev_min, 
                test_days
            )
            
            fold_result = WalkForwardFold(
                fold_index=fold.fold_index,
                train_start=fold.train_start,
                train_end=fold.train_end,
                test_start=fold.test_start,
                test_end=fold.test_end,
                in_sample_optimal_ev_min=train_result.optimal_ev_min,
                in_sample_sharpe=train_result.optimal_metrics.sharpe_ratio,
                in_sample_trades_per_day=train_result.optimal_metrics.trades_per_day,
                out_of_sample_sharpe=test_metrics.sharpe_ratio,
                out_of_sample_trades_per_day=test_metrics.trades_per_day,
                out_of_sample_net_ev=test_metrics.net_ev,
            )
            walk_forward_results.append(fold_result)
            all_out_of_sample_sharpes.append(test_metrics.sharpe_ratio)
        
        # Compute overall metrics using all data
        total_days = (sorted_trades[-1].timestamp - sorted_trades[0].timestamp) / 86400.0
        overall_result = self.sweep(sorted_trades, max(total_days, 1.0))
        overall_result.walk_forward_results = walk_forward_results
        
        return overall_result
    
    def _generate_thresholds(self) -> List[float]:
        """Generate list of threshold values to sweep."""
        thresholds = []
        current = self.sweep_start
        while current <= self.sweep_end + 1e-9:  # Small epsilon for float comparison
            thresholds.append(round(current, 4))
            current += self.sweep_step
        return thresholds
    
    def _compute_metrics_for_threshold(
        self,
        trades: List[BacktestTrade],
        ev_min: float,
        trading_days: float,
    ) -> ThresholdMetrics:
        """Compute metrics for a single EV_Min threshold."""
        accepted_trades = []
        rejected_count = 0
        
        for trade in trades:
            # Calculate L, G, R
            L_bps, G_bps, R = calculate_L_G_R(
                trade.entry_price,
                trade.stop_loss,
                trade.take_profit,
                trade.side,
            )
            
            # Skip invalid trades
            if L_bps <= 0 or math.isnan(R) or R <= 0:
                rejected_count += 1
                continue
            
            # Calculate total cost
            total_cost_bps = (
                trade.spread_bps + 
                trade.fee_bps + 
                trade.slippage_bps + 
                trade.adverse_selection_bps
            )
            
            # Calculate C
            C = calculate_cost_ratio(total_cost_bps, L_bps)
            
            # Skip if costs exceed stop loss
            if C > 1.0:
                rejected_count += 1
                continue
            
            # Calculate EV
            EV = calculate_ev(trade.p_hat, R, C)
            
            # Apply threshold
            if EV >= ev_min:
                accepted_trades.append((trade, EV, R, C, L_bps, G_bps))
            else:
                rejected_count += 1
        
        # Compute metrics from accepted trades
        total_signals = len(trades)
        accepted_count = len(accepted_trades)
        trades_per_day = accepted_count / trading_days if trading_days > 0 else 0.0
        
        if not accepted_trades:
            return ThresholdMetrics(
                ev_min=ev_min,
                total_signals=total_signals,
                accepted_trades=0,
                rejected_trades=rejected_count,
                trades_per_day=0.0,
                gross_ev=0.0,
                net_ev=0.0,
                total_pnl_bps=0.0,
                avg_pnl_bps=0.0,
                max_drawdown_bps=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                cvar_95=0.0,
                win_rate=0.0,
                avg_hold_time_seconds=0.0,
                profit_factor=0.0,
                acceptance_rate=0.0,
            )
        
        # Calculate PnL metrics
        pnls = [t[0].pnl_bps for t in accepted_trades]
        evs = [t[1] for t in accepted_trades]
        
        gross_ev = sum(evs)
        net_ev = sum(pnls) / 10000.0  # Convert bps to ratio
        total_pnl_bps = sum(pnls)
        avg_pnl_bps = total_pnl_bps / accepted_count
        
        # Calculate drawdown
        max_drawdown_bps = self._calculate_max_drawdown(pnls)
        
        # Calculate Sharpe and Sortino
        sharpe_ratio = self._calculate_sharpe(pnls)
        sortino_ratio = self._calculate_sortino(pnls)
        
        # Calculate CVaR 95%
        cvar_95 = self._calculate_cvar(pnls, 0.95)
        
        # Win rate
        wins = sum(1 for t in accepted_trades if t[0].outcome == 1)
        win_rate = wins / accepted_count
        
        # Average hold time
        avg_hold_time = sum(t[0].hold_time_seconds for t in accepted_trades) / accepted_count
        
        # Profit factor
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Acceptance rate
        acceptance_rate = accepted_count / total_signals if total_signals > 0 else 0.0
        
        return ThresholdMetrics(
            ev_min=ev_min,
            total_signals=total_signals,
            accepted_trades=accepted_count,
            rejected_trades=rejected_count,
            trades_per_day=trades_per_day,
            gross_ev=gross_ev,
            net_ev=net_ev,
            total_pnl_bps=total_pnl_bps,
            avg_pnl_bps=avg_pnl_bps,
            max_drawdown_bps=max_drawdown_bps,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            cvar_95=cvar_95,
            win_rate=win_rate,
            avg_hold_time_seconds=avg_hold_time,
            profit_factor=profit_factor,
            acceptance_rate=acceptance_rate,
        )

    
    def _find_optimal_threshold(
        self,
        metrics_list: List[ThresholdMetrics],
    ) -> Tuple[float, ThresholdMetrics, str]:
        """
        Find optimal EV_Min based on risk-adjusted return.
        
        Requirements: 8.4, 8.8
        """
        # Filter out thresholds with too few trades
        valid_metrics = [
            m for m in metrics_list 
            if m.trades_per_day >= self.min_trades_per_day
        ]
        
        if not valid_metrics:
            # Fall back to threshold with most trades if none meet minimum
            best = max(metrics_list, key=lambda m: m.trades_per_day)
            return (
                best.ev_min, 
                best, 
                f"No threshold meets min_trades_per_day={self.min_trades_per_day}, "
                f"using threshold with most trades"
            )
        
        # Find best by Sharpe ratio (primary) or Sortino (secondary)
        best_sharpe = max(valid_metrics, key=lambda m: m.sharpe_ratio)
        best_sortino = max(valid_metrics, key=lambda m: m.sortino_ratio)
        
        # Prefer Sharpe unless Sortino is significantly better
        if best_sortino.sortino_ratio > best_sharpe.sharpe_ratio * 1.2:
            return (
                best_sortino.ev_min,
                best_sortino,
                f"Optimal by Sortino ratio ({best_sortino.sortino_ratio:.3f})"
            )
        
        return (
            best_sharpe.ev_min,
            best_sharpe,
            f"Optimal by Sharpe ratio ({best_sharpe.sharpe_ratio:.3f})"
        )
    
    def _find_knee_point(
        self,
        metrics_list: List[ThresholdMetrics],
    ) -> Optional[float]:
        """
        Find the knee point where trades increase but net EV doesn't improve.
        
        The knee point is where lowering EV_Min further increases trade count
        but doesn't proportionally increase net EV.
        
        Requirements: 8.7
        """
        if len(metrics_list) < 3:
            return None
        
        # Sort by ev_min descending (high to low threshold)
        sorted_metrics = sorted(metrics_list, key=lambda m: m.ev_min, reverse=True)
        
        # Look for point where trade increase rate exceeds net EV increase rate
        for i in range(1, len(sorted_metrics) - 1):
            prev = sorted_metrics[i - 1]
            curr = sorted_metrics[i]
            next_m = sorted_metrics[i + 1]
            
            # Skip if no trades
            if curr.accepted_trades == 0 or prev.accepted_trades == 0:
                continue
            
            # Calculate rate of change
            trade_increase = (curr.accepted_trades - prev.accepted_trades) / max(prev.accepted_trades, 1)
            
            if prev.net_ev != 0:
                ev_increase = (curr.net_ev - prev.net_ev) / abs(prev.net_ev)
            else:
                ev_increase = curr.net_ev
            
            # Knee point: trades increasing but EV not improving proportionally
            if trade_increase > 0.1 and ev_increase < trade_increase * 0.5:
                return curr.ev_min
        
        return None
    
    def _calculate_max_drawdown(self, pnls: List[float]) -> float:
        """Calculate maximum drawdown in bps."""
        if not pnls:
            return 0.0
        
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        
        for pnl in pnls:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            drawdown = peak - cumulative
            if drawdown > max_dd:
                max_dd = drawdown
        
        return max_dd
    
    def _calculate_sharpe(self, pnls: List[float], risk_free_rate: float = 0.0) -> float:
        """Calculate Sharpe ratio from PnL series."""
        if len(pnls) < 2:
            return 0.0
        
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
        std_dev = math.sqrt(variance) if variance > 0 else 0.0
        
        if std_dev == 0:
            return 0.0 if mean_pnl <= risk_free_rate else float('inf')
        
        return (mean_pnl - risk_free_rate) / std_dev
    
    def _calculate_sortino(self, pnls: List[float], target_return: float = 0.0) -> float:
        """Calculate Sortino ratio (downside deviation only)."""
        if len(pnls) < 2:
            return 0.0
        
        mean_pnl = sum(pnls) / len(pnls)
        
        # Calculate downside deviation
        downside_returns = [min(0, p - target_return) for p in pnls]
        downside_variance = sum(d ** 2 for d in downside_returns) / len(pnls)
        downside_dev = math.sqrt(downside_variance) if downside_variance > 0 else 0.0
        
        if downside_dev == 0:
            return 0.0 if mean_pnl <= target_return else float('inf')
        
        return (mean_pnl - target_return) / downside_dev
    
    def _calculate_cvar(self, pnls: List[float], confidence: float = 0.95) -> float:
        """Calculate Conditional Value at Risk (Expected Shortfall)."""
        if not pnls:
            return 0.0
        
        sorted_pnls = sorted(pnls)
        cutoff_index = int(len(sorted_pnls) * (1 - confidence))
        
        if cutoff_index == 0:
            return sorted_pnls[0]
        
        tail_losses = sorted_pnls[:cutoff_index]
        return sum(tail_losses) / len(tail_losses) if tail_losses else 0.0
    
    def _create_walk_forward_folds(
        self,
        sorted_trades: List[BacktestTrade],
        n_folds: int,
        train_ratio: float,
    ) -> List[WalkForwardFold]:
        """Create walk-forward validation folds."""
        if not sorted_trades:
            return []
        
        start_time = sorted_trades[0].timestamp
        end_time = sorted_trades[-1].timestamp
        total_duration = end_time - start_time
        
        if total_duration <= 0:
            return []
        
        # Calculate fold size
        fold_duration = total_duration / n_folds
        train_duration = fold_duration * train_ratio
        test_duration = fold_duration * (1 - train_ratio)
        
        folds = []
        for i in range(n_folds):
            fold_start = start_time + i * fold_duration
            train_end = fold_start + train_duration
            test_end = fold_start + fold_duration
            
            folds.append(WalkForwardFold(
                fold_index=i,
                train_start=fold_start,
                train_end=train_end,
                test_start=train_end,
                test_end=test_end,
                in_sample_optimal_ev_min=0.0,
                in_sample_sharpe=0.0,
                in_sample_trades_per_day=0.0,
                out_of_sample_sharpe=0.0,
                out_of_sample_trades_per_day=0.0,
                out_of_sample_net_ev=0.0,
            ))
        
        return folds


def generate_sweep_report(result: SweepResult) -> str:
    """
    Generate a human-readable report from sweep results.
    
    Requirements: 8.6
    """
    lines = [
        "=" * 60,
        "EV Threshold Sweep Report",
        "=" * 60,
        "",
        f"Optimal EV_Min: {result.optimal_ev_min:.4f}",
        f"Recommendation: {result.recommendation_reason}",
        "",
    ]
    
    if result.knee_ev_min is not None:
        lines.append(f"Knee Point: {result.knee_ev_min:.4f}")
        lines.append("")
    
    # Optimal metrics summary
    opt = result.optimal_metrics
    lines.extend([
        "Optimal Threshold Metrics:",
        f"  Trades per day: {opt.trades_per_day:.2f}",
        f"  Win rate: {opt.win_rate:.1%}",
        f"  Sharpe ratio: {opt.sharpe_ratio:.3f}",
        f"  Sortino ratio: {opt.sortino_ratio:.3f}",
        f"  Net EV: {opt.net_ev:.4f}",
        f"  Max drawdown: {opt.max_drawdown_bps:.2f} bps",
        f"  CVaR 95%: {opt.cvar_95:.2f} bps",
        f"  Profit factor: {opt.profit_factor:.2f}",
        f"  Acceptance rate: {opt.acceptance_rate:.1%}",
        "",
    ])
    
    # Walk-forward results if available
    if result.walk_forward_results:
        lines.extend([
            "Walk-Forward Validation:",
            "-" * 40,
        ])
        for fold in result.walk_forward_results:
            lines.extend([
                f"  Fold {fold.fold_index + 1}:",
                f"    In-sample EV_Min: {fold.in_sample_optimal_ev_min:.4f}",
                f"    In-sample Sharpe: {fold.in_sample_sharpe:.3f}",
                f"    Out-of-sample Sharpe: {fold.out_of_sample_sharpe:.3f}",
                f"    Out-of-sample trades/day: {fold.out_of_sample_trades_per_day:.2f}",
            ])
        lines.append("")
    
    # Summary table
    lines.extend([
        "Threshold Summary (top 10 by Sharpe):",
        "-" * 60,
        f"{'EV_Min':>8} {'Trades/Day':>12} {'Win Rate':>10} {'Sharpe':>8} {'Net EV':>10}",
        "-" * 60,
    ])
    
    # Sort by Sharpe and show top 10
    sorted_metrics = sorted(
        result.metrics_by_threshold, 
        key=lambda m: m.sharpe_ratio, 
        reverse=True
    )[:10]
    
    for m in sorted_metrics:
        lines.append(
            f"{m.ev_min:>8.4f} {m.trades_per_day:>12.2f} {m.win_rate:>10.1%} "
            f"{m.sharpe_ratio:>8.3f} {m.net_ev:>10.4f}"
        )
    
    lines.append("=" * 60)
    
    return "\n".join(lines)



class WalkForwardValidator:
    """
    Walk-forward validation for EV threshold optimization.
    
    Uses rolling windows to validate that optimal thresholds found on
    training data perform well on out-of-sample test data.
    
    Requirements: 8.3
    """
    
    def __init__(
        self,
        sweeper: EVThresholdSweeper,
        n_folds: int = 5,
        train_ratio: float = 0.7,
        min_train_trades: int = 50,
        min_test_trades: int = 20,
    ):
        """
        Initialize walk-forward validator.
        
        Args:
            sweeper: EVThresholdSweeper instance for threshold optimization
            n_folds: Number of walk-forward folds
            train_ratio: Ratio of each fold to use for training
            min_train_trades: Minimum trades required in training set
            min_test_trades: Minimum trades required in test set
        """
        self.sweeper = sweeper
        self.n_folds = n_folds
        self.train_ratio = train_ratio
        self.min_train_trades = min_train_trades
        self.min_test_trades = min_test_trades
    
    def validate(
        self,
        trades: List[BacktestTrade],
    ) -> WalkForwardValidationResult:
        """
        Perform walk-forward validation on historical trades.
        
        Args:
            trades: List of historical trades sorted by timestamp
            
        Returns:
            WalkForwardValidationResult with fold-by-fold analysis
        """
        if not trades:
            raise ValueError("Must provide trades for validation")
        
        # Sort trades by timestamp
        sorted_trades = sorted(trades, key=lambda t: t.timestamp)
        
        # Create time-based folds
        folds = self._create_time_folds(sorted_trades)
        
        fold_results = []
        optimal_thresholds = []
        
        for fold_idx, (train_trades, test_trades) in enumerate(folds):
            if len(train_trades) < self.min_train_trades:
                continue
            if len(test_trades) < self.min_test_trades:
                continue
            
            # Calculate trading days
            train_days = self._calculate_trading_days(train_trades)
            test_days = self._calculate_trading_days(test_trades)
            
            # Find optimal threshold on training data
            train_result = self.sweeper.sweep(train_trades, train_days)
            optimal_ev_min = train_result.optimal_ev_min
            optimal_thresholds.append(optimal_ev_min)
            
            # Evaluate on test data
            test_metrics = self.sweeper._compute_metrics_for_threshold(
                test_trades, optimal_ev_min, test_days
            )
            
            # Calculate performance degradation
            in_sample_sharpe = train_result.optimal_metrics.sharpe_ratio
            out_sample_sharpe = test_metrics.sharpe_ratio
            
            degradation = 0.0
            if in_sample_sharpe > 0:
                degradation = (in_sample_sharpe - out_sample_sharpe) / in_sample_sharpe
            
            fold_results.append(WalkForwardFoldResult(
                fold_index=fold_idx,
                train_trades=len(train_trades),
                test_trades=len(test_trades),
                optimal_ev_min=optimal_ev_min,
                in_sample_sharpe=in_sample_sharpe,
                in_sample_trades_per_day=train_result.optimal_metrics.trades_per_day,
                in_sample_win_rate=train_result.optimal_metrics.win_rate,
                out_sample_sharpe=out_sample_sharpe,
                out_sample_trades_per_day=test_metrics.trades_per_day,
                out_sample_win_rate=test_metrics.win_rate,
                out_sample_net_ev=test_metrics.net_ev,
                performance_degradation=degradation,
            ))
        
        # Calculate aggregate statistics
        if fold_results:
            avg_degradation = sum(f.performance_degradation for f in fold_results) / len(fold_results)
            avg_out_sample_sharpe = sum(f.out_sample_sharpe for f in fold_results) / len(fold_results)
            threshold_stability = self._calculate_threshold_stability(optimal_thresholds)
        else:
            avg_degradation = 0.0
            avg_out_sample_sharpe = 0.0
            threshold_stability = 0.0
        
        # Recommend final threshold
        if optimal_thresholds:
            recommended_ev_min = sum(optimal_thresholds) / len(optimal_thresholds)
        else:
            recommended_ev_min = self.sweeper.sweep_start
        
        return WalkForwardValidationResult(
            fold_results=fold_results,
            recommended_ev_min=recommended_ev_min,
            avg_performance_degradation=avg_degradation,
            avg_out_sample_sharpe=avg_out_sample_sharpe,
            threshold_stability=threshold_stability,
            is_robust=avg_degradation < 0.3 and threshold_stability > 0.7,
        )
    
    def _create_time_folds(
        self,
        sorted_trades: List[BacktestTrade],
    ) -> List[Tuple[List[BacktestTrade], List[BacktestTrade]]]:
        """Create time-based train/test splits."""
        if not sorted_trades:
            return []
        
        start_time = sorted_trades[0].timestamp
        end_time = sorted_trades[-1].timestamp
        total_duration = end_time - start_time
        
        if total_duration <= 0:
            return []
        
        fold_duration = total_duration / self.n_folds
        folds = []
        
        for i in range(self.n_folds):
            fold_start = start_time + i * fold_duration
            fold_end = fold_start + fold_duration
            train_end = fold_start + fold_duration * self.train_ratio
            
            train_trades = [
                t for t in sorted_trades 
                if fold_start <= t.timestamp < train_end
            ]
            test_trades = [
                t for t in sorted_trades 
                if train_end <= t.timestamp < fold_end
            ]
            
            folds.append((train_trades, test_trades))
        
        return folds
    
    def _calculate_trading_days(self, trades: List[BacktestTrade]) -> float:
        """Calculate number of trading days from trade timestamps."""
        if len(trades) < 2:
            return 1.0
        
        start = min(t.timestamp for t in trades)
        end = max(t.timestamp for t in trades)
        
        return max((end - start) / 86400.0, 1.0)
    
    def _calculate_threshold_stability(self, thresholds: List[float]) -> float:
        """
        Calculate stability of optimal thresholds across folds.
        
        Returns value between 0 and 1, where 1 means perfectly stable.
        """
        if len(thresholds) < 2:
            return 1.0
        
        mean_threshold = sum(thresholds) / len(thresholds)
        if mean_threshold == 0:
            return 1.0
        
        variance = sum((t - mean_threshold) ** 2 for t in thresholds) / len(thresholds)
        std_dev = math.sqrt(variance)
        
        # Coefficient of variation (lower is more stable)
        cv = std_dev / mean_threshold if mean_threshold > 0 else 0
        
        # Convert to stability score (1 - normalized CV)
        stability = max(0.0, 1.0 - cv)
        
        return stability


@dataclass
class WalkForwardFoldResult:
    """Results from a single walk-forward fold."""
    fold_index: int
    train_trades: int
    test_trades: int
    optimal_ev_min: float
    
    # In-sample metrics
    in_sample_sharpe: float
    in_sample_trades_per_day: float
    in_sample_win_rate: float
    
    # Out-of-sample metrics
    out_sample_sharpe: float
    out_sample_trades_per_day: float
    out_sample_win_rate: float
    out_sample_net_ev: float
    
    # Performance comparison
    performance_degradation: float  # (in_sample - out_sample) / in_sample


@dataclass
class WalkForwardValidationResult:
    """Aggregate results from walk-forward validation."""
    fold_results: List[WalkForwardFoldResult]
    recommended_ev_min: float
    avg_performance_degradation: float
    avg_out_sample_sharpe: float
    threshold_stability: float  # 0-1, higher is more stable
    is_robust: bool  # True if results are robust across folds


def generate_walk_forward_report(result: WalkForwardValidationResult) -> str:
    """Generate a human-readable walk-forward validation report."""
    lines = [
        "=" * 60,
        "Walk-Forward Validation Report",
        "=" * 60,
        "",
        f"Recommended EV_Min: {result.recommended_ev_min:.4f}",
        f"Threshold Stability: {result.threshold_stability:.1%}",
        f"Avg Performance Degradation: {result.avg_performance_degradation:.1%}",
        f"Avg Out-of-Sample Sharpe: {result.avg_out_sample_sharpe:.3f}",
        f"Is Robust: {'Yes' if result.is_robust else 'No'}",
        "",
        "Fold-by-Fold Results:",
        "-" * 60,
    ]
    
    for fold in result.fold_results:
        lines.extend([
            f"Fold {fold.fold_index + 1}:",
            f"  Train/Test trades: {fold.train_trades}/{fold.test_trades}",
            f"  Optimal EV_Min: {fold.optimal_ev_min:.4f}",
            f"  In-sample Sharpe: {fold.in_sample_sharpe:.3f}",
            f"  Out-sample Sharpe: {fold.out_sample_sharpe:.3f}",
            f"  Degradation: {fold.performance_degradation:.1%}",
            "",
        ])
    
    lines.append("=" * 60)
    
    return "\n".join(lines)



class KneeDetector:
    """
    Detects the knee point in EV threshold sweep results.
    
    The knee point is where lowering EV_Min further increases trade count
    significantly but doesn't proportionally increase net EV or risk-adjusted
    returns.
    
    Requirements: 8.7
    """
    
    def __init__(
        self,
        trade_increase_threshold: float = 0.15,
        ev_improvement_ratio: float = 0.5,
        use_curvature: bool = True,
    ):
        """
        Initialize knee detector.
        
        Args:
            trade_increase_threshold: Minimum trade increase rate to consider
            ev_improvement_ratio: Ratio of EV improvement to trade increase
            use_curvature: Whether to use curvature-based detection
        """
        self.trade_increase_threshold = trade_increase_threshold
        self.ev_improvement_ratio = ev_improvement_ratio
        self.use_curvature = use_curvature
    
    def detect(
        self,
        metrics_list: List[ThresholdMetrics],
    ) -> KneeDetectionResult:
        """
        Detect the knee point in threshold sweep results.
        
        Args:
            metrics_list: List of metrics for each threshold
            
        Returns:
            KneeDetectionResult with detected knee point and analysis
        """
        if len(metrics_list) < 3:
            return KneeDetectionResult(
                knee_ev_min=None,
                knee_index=None,
                detection_method="insufficient_data",
                confidence=0.0,
                analysis="Not enough data points for knee detection",
            )
        
        # Sort by ev_min descending (high to low threshold)
        sorted_metrics = sorted(metrics_list, key=lambda m: m.ev_min, reverse=True)
        
        # Try multiple detection methods
        results = []
        
        # Method 1: Rate of change analysis
        roc_knee = self._detect_by_rate_of_change(sorted_metrics)
        if roc_knee is not None:
            results.append(("rate_of_change", roc_knee))
        
        # Method 2: Curvature analysis (if enabled)
        if self.use_curvature:
            curv_knee = self._detect_by_curvature(sorted_metrics)
            if curv_knee is not None:
                results.append(("curvature", curv_knee))
        
        # Method 3: Efficiency frontier
        eff_knee = self._detect_by_efficiency(sorted_metrics)
        if eff_knee is not None:
            results.append(("efficiency", eff_knee))
        
        if not results:
            return KneeDetectionResult(
                knee_ev_min=None,
                knee_index=None,
                detection_method="none",
                confidence=0.0,
                analysis="No knee point detected",
            )
        
        # Use consensus if multiple methods agree
        knee_values = [r[1] for r in results]
        
        # Find most common knee point (within tolerance)
        best_knee = self._find_consensus_knee(knee_values, sorted_metrics)
        
        # Calculate confidence based on method agreement
        confidence = len([k for k in knee_values if abs(k - best_knee) < 0.02]) / len(results)
        
        # Find index
        knee_index = None
        for i, m in enumerate(sorted_metrics):
            if abs(m.ev_min - best_knee) < 0.001:
                knee_index = i
                break
        
        return KneeDetectionResult(
            knee_ev_min=best_knee,
            knee_index=knee_index,
            detection_method=results[0][0] if results else "none",
            confidence=confidence,
            analysis=self._generate_analysis(sorted_metrics, best_knee, knee_index),
        )
    
    def _detect_by_rate_of_change(
        self,
        sorted_metrics: List[ThresholdMetrics],
    ) -> Optional[float]:
        """Detect knee by analyzing rate of change."""
        for i in range(1, len(sorted_metrics) - 1):
            prev = sorted_metrics[i - 1]
            curr = sorted_metrics[i]
            
            if prev.accepted_trades == 0 or curr.accepted_trades == 0:
                continue
            
            # Calculate trade increase rate
            trade_increase = (curr.accepted_trades - prev.accepted_trades) / max(prev.accepted_trades, 1)
            
            # Calculate EV improvement rate
            if prev.net_ev != 0:
                ev_change = (curr.net_ev - prev.net_ev) / abs(prev.net_ev)
            else:
                ev_change = curr.net_ev if curr.net_ev != 0 else 0
            
            # Knee: trades increasing significantly but EV not improving proportionally
            if (trade_increase > self.trade_increase_threshold and 
                ev_change < trade_increase * self.ev_improvement_ratio):
                return curr.ev_min
        
        return None
    
    def _detect_by_curvature(
        self,
        sorted_metrics: List[ThresholdMetrics],
    ) -> Optional[float]:
        """Detect knee by finding maximum curvature point."""
        if len(sorted_metrics) < 5:
            return None
        
        # Extract trades and net_ev as coordinates
        x = [m.accepted_trades for m in sorted_metrics]
        y = [m.net_ev for m in sorted_metrics]
        
        # Normalize to [0, 1] range
        x_min, x_max = min(x), max(x)
        y_min, y_max = min(y), max(y)
        
        if x_max == x_min or y_max == y_min:
            return None
        
        x_norm = [(xi - x_min) / (x_max - x_min) for xi in x]
        y_norm = [(yi - y_min) / (y_max - y_min) for yi in y]
        
        # Calculate curvature at each point
        max_curvature = 0.0
        max_curv_idx = None
        
        for i in range(1, len(sorted_metrics) - 1):
            # Approximate second derivative
            dx1 = x_norm[i] - x_norm[i-1]
            dx2 = x_norm[i+1] - x_norm[i]
            dy1 = y_norm[i] - y_norm[i-1]
            dy2 = y_norm[i+1] - y_norm[i]
            
            if dx1 == 0 or dx2 == 0:
                continue
            
            # First derivatives
            dydx1 = dy1 / dx1
            dydx2 = dy2 / dx2
            
            # Second derivative approximation
            d2ydx2 = (dydx2 - dydx1) / ((dx1 + dx2) / 2)
            
            # Curvature formula: |y''| / (1 + y'^2)^(3/2)
            avg_dydx = (dydx1 + dydx2) / 2
            curvature = abs(d2ydx2) / ((1 + avg_dydx**2) ** 1.5)
            
            if curvature > max_curvature:
                max_curvature = curvature
                max_curv_idx = i
        
        if max_curv_idx is not None:
            return sorted_metrics[max_curv_idx].ev_min
        
        return None
    
    def _detect_by_efficiency(
        self,
        sorted_metrics: List[ThresholdMetrics],
    ) -> Optional[float]:
        """Detect knee by finding efficiency frontier break point."""
        # Calculate efficiency: net_ev per trade
        efficiencies = []
        for m in sorted_metrics:
            if m.accepted_trades > 0:
                efficiency = m.net_ev / m.accepted_trades
            else:
                efficiency = 0.0
            efficiencies.append((m.ev_min, efficiency, m.accepted_trades))
        
        # Find point where efficiency drops significantly
        for i in range(1, len(efficiencies)):
            prev_eff = efficiencies[i-1][1]
            curr_eff = efficiencies[i][1]
            
            if prev_eff > 0:
                eff_drop = (prev_eff - curr_eff) / prev_eff
                if eff_drop > 0.2:  # 20% efficiency drop
                    return efficiencies[i][0]
        
        return None
    
    def _find_consensus_knee(
        self,
        knee_values: List[float],
        sorted_metrics: List[ThresholdMetrics],
    ) -> float:
        """Find consensus knee point from multiple detection methods."""
        if not knee_values:
            return sorted_metrics[len(sorted_metrics) // 2].ev_min
        
        # Simple average for now
        return sum(knee_values) / len(knee_values)
    
    def _generate_analysis(
        self,
        sorted_metrics: List[ThresholdMetrics],
        knee_ev_min: float,
        knee_index: Optional[int],
    ) -> str:
        """Generate analysis text for the knee point."""
        if knee_index is None:
            return "Knee point detected but index not found"
        
        knee_metrics = sorted_metrics[knee_index]
        
        # Compare to adjacent thresholds
        analysis_parts = [
            f"Knee detected at EV_Min = {knee_ev_min:.4f}",
            f"At this threshold: {knee_metrics.accepted_trades} trades, "
            f"Sharpe = {knee_metrics.sharpe_ratio:.3f}",
        ]
        
        if knee_index > 0:
            higher = sorted_metrics[knee_index - 1]
            trade_diff = knee_metrics.accepted_trades - higher.accepted_trades
            ev_diff = knee_metrics.net_ev - higher.net_ev
            analysis_parts.append(
                f"Lowering threshold adds {trade_diff} trades but only "
                f"{ev_diff:.4f} net EV"
            )
        
        return ". ".join(analysis_parts)


@dataclass
class KneeDetectionResult:
    """Result of knee point detection."""
    knee_ev_min: Optional[float]
    knee_index: Optional[int]
    detection_method: str
    confidence: float  # 0-1, based on method agreement
    analysis: str



class ThresholdRecommender:
    """
    Recommends optimal EV_Min threshold based on backtest results.
    
    Uses multiple criteria including Sharpe/Sortino ratios, trade frequency,
    and robustness across walk-forward folds.
    
    Requirements: 8.4, 8.8
    """
    
    def __init__(
        self,
        min_trades_per_day: int = 5,
        min_sharpe: float = 0.5,
        min_win_rate: float = 0.4,
        prefer_robustness: bool = True,
        risk_metric: str = "sharpe",  # "sharpe" or "sortino"
    ):
        """
        Initialize threshold recommender.
        
        Args:
            min_trades_per_day: Minimum trades per day to accept (Req 8.4)
            min_sharpe: Minimum Sharpe ratio to consider
            min_win_rate: Minimum win rate to consider
            prefer_robustness: Whether to prefer robust thresholds over optimal
            risk_metric: Primary risk metric ("sharpe" or "sortino")
        """
        self.min_trades_per_day = min_trades_per_day
        self.min_sharpe = min_sharpe
        self.min_win_rate = min_win_rate
        self.prefer_robustness = prefer_robustness
        self.risk_metric = risk_metric
    
    def recommend(
        self,
        sweep_result: SweepResult,
        walk_forward_result: Optional[WalkForwardValidationResult] = None,
    ) -> ThresholdRecommendation:
        """
        Generate threshold recommendation from sweep and validation results.
        
        Args:
            sweep_result: Results from threshold sweep
            walk_forward_result: Optional walk-forward validation results
            
        Returns:
            ThresholdRecommendation with recommended threshold and reasoning
        """
        candidates = self._filter_candidates(sweep_result.metrics_by_threshold)
        
        if not candidates:
            return self._handle_no_candidates(sweep_result)
        
        # Score each candidate
        scored_candidates = []
        for metrics in candidates:
            score = self._score_candidate(metrics, sweep_result, walk_forward_result)
            scored_candidates.append((metrics, score))
        
        # Sort by score descending
        scored_candidates.sort(key=lambda x: x[1].total_score, reverse=True)
        
        best_metrics, best_score = scored_candidates[0]
        
        # Generate recommendation
        return ThresholdRecommendation(
            recommended_ev_min=best_metrics.ev_min,
            confidence=best_score.confidence,
            primary_reason=best_score.primary_reason,
            metrics=best_metrics,
            score_breakdown=best_score,
            alternatives=[m.ev_min for m, _ in scored_candidates[1:4]],
            warnings=self._generate_warnings(best_metrics, walk_forward_result),
        )
    
    def _filter_candidates(
        self,
        metrics_list: List[ThresholdMetrics],
    ) -> List[ThresholdMetrics]:
        """Filter candidates based on minimum requirements."""
        candidates = []
        
        for m in metrics_list:
            # Check minimum trades per day (Requirement 8.4)
            if m.trades_per_day < self.min_trades_per_day:
                continue
            
            # Check minimum Sharpe
            if m.sharpe_ratio < self.min_sharpe:
                continue
            
            # Check minimum win rate
            if m.win_rate < self.min_win_rate:
                continue
            
            candidates.append(m)
        
        return candidates
    
    def _score_candidate(
        self,
        metrics: ThresholdMetrics,
        sweep_result: SweepResult,
        walk_forward_result: Optional[WalkForwardValidationResult],
    ) -> "CandidateScore":
        """Score a candidate threshold."""
        scores = {}
        
        # Risk-adjusted return score (primary)
        if self.risk_metric == "sortino":
            risk_score = min(metrics.sortino_ratio / 2.0, 1.0)  # Normalize to 0-1
            scores["risk_adjusted"] = risk_score
        else:
            risk_score = min(metrics.sharpe_ratio / 2.0, 1.0)
            scores["risk_adjusted"] = risk_score
        
        # Trade frequency score
        max_trades = max(m.trades_per_day for m in sweep_result.metrics_by_threshold)
        if max_trades > 0:
            freq_score = metrics.trades_per_day / max_trades
        else:
            freq_score = 0.0
        scores["frequency"] = freq_score
        
        # Win rate score
        scores["win_rate"] = metrics.win_rate
        
        # Profit factor score
        pf_score = min(metrics.profit_factor / 2.0, 1.0) if metrics.profit_factor < float('inf') else 1.0
        scores["profit_factor"] = pf_score
        
        # Drawdown score (inverse - lower is better)
        max_dd = max(m.max_drawdown_bps for m in sweep_result.metrics_by_threshold)
        if max_dd > 0:
            dd_score = 1.0 - (metrics.max_drawdown_bps / max_dd)
        else:
            dd_score = 1.0
        scores["drawdown"] = dd_score
        
        # Robustness score (from walk-forward if available)
        robustness_score = 0.5  # Default
        if walk_forward_result and walk_forward_result.is_robust:
            robustness_score = walk_forward_result.threshold_stability
        scores["robustness"] = robustness_score
        
        # Calculate weighted total
        weights = {
            "risk_adjusted": 0.30,
            "frequency": 0.15,
            "win_rate": 0.15,
            "profit_factor": 0.15,
            "drawdown": 0.10,
            "robustness": 0.15 if self.prefer_robustness else 0.05,
        }
        
        total_score = sum(scores[k] * weights[k] for k in scores)
        
        # Determine primary reason
        best_component = max(scores.items(), key=lambda x: x[1] * weights.get(x[0], 0))
        primary_reason = self._reason_from_component(best_component[0], metrics)
        
        # Calculate confidence
        confidence = self._calculate_confidence(scores, walk_forward_result)
        
        return CandidateScore(
            total_score=total_score,
            component_scores=scores,
            primary_reason=primary_reason,
            confidence=confidence,
        )
    
    def _reason_from_component(self, component: str, metrics: ThresholdMetrics) -> str:
        """Generate reason text from best scoring component."""
        reasons = {
            "risk_adjusted": f"Best risk-adjusted return (Sharpe={metrics.sharpe_ratio:.3f})",
            "frequency": f"Good trade frequency ({metrics.trades_per_day:.1f}/day)",
            "win_rate": f"Strong win rate ({metrics.win_rate:.1%})",
            "profit_factor": f"High profit factor ({metrics.profit_factor:.2f})",
            "drawdown": f"Low drawdown ({metrics.max_drawdown_bps:.1f} bps)",
            "robustness": "Robust across validation folds",
        }
        return reasons.get(component, "Balanced performance")
    
    def _calculate_confidence(
        self,
        scores: Dict[str, float],
        walk_forward_result: Optional[WalkForwardValidationResult],
    ) -> float:
        """Calculate confidence in the recommendation."""
        # Base confidence from score consistency
        score_values = list(scores.values())
        avg_score = sum(score_values) / len(score_values)
        variance = sum((s - avg_score) ** 2 for s in score_values) / len(score_values)
        consistency = 1.0 - min(math.sqrt(variance), 1.0)
        
        # Boost from walk-forward validation
        wf_boost = 0.0
        if walk_forward_result:
            if walk_forward_result.is_robust:
                wf_boost = 0.2
            elif walk_forward_result.threshold_stability > 0.5:
                wf_boost = 0.1
        
        return min(consistency + wf_boost, 1.0)
    
    def _handle_no_candidates(self, sweep_result: SweepResult) -> "ThresholdRecommendation":
        """Handle case where no candidates meet minimum requirements."""
        # Find best available even if below thresholds
        best = max(
            sweep_result.metrics_by_threshold,
            key=lambda m: m.sharpe_ratio if m.trades_per_day > 0 else -float('inf')
        )
        
        return ThresholdRecommendation(
            recommended_ev_min=best.ev_min,
            confidence=0.3,
            primary_reason=f"No threshold meets minimum requirements "
                          f"(min_trades={self.min_trades_per_day}/day)",
            metrics=best,
            score_breakdown=CandidateScore(
                total_score=0.0,
                component_scores={},
                primary_reason="Fallback selection",
                confidence=0.3,
            ),
            alternatives=[],
            warnings=[
                f"Trades per day ({best.trades_per_day:.1f}) below minimum ({self.min_trades_per_day})",
                "Consider adjusting minimum requirements or gathering more data",
            ],
        )
    
    def _generate_warnings(
        self,
        metrics: ThresholdMetrics,
        walk_forward_result: Optional[WalkForwardValidationResult],
    ) -> List[str]:
        """Generate warnings about the recommendation."""
        warnings = []
        
        if metrics.trades_per_day < self.min_trades_per_day * 1.5:
            warnings.append(
                f"Trade frequency ({metrics.trades_per_day:.1f}/day) is close to minimum"
            )
        
        if metrics.max_drawdown_bps > 100:
            warnings.append(
                f"Max drawdown ({metrics.max_drawdown_bps:.1f} bps) is significant"
            )
        
        if walk_forward_result and not walk_forward_result.is_robust:
            warnings.append(
                "Walk-forward validation shows inconsistent performance"
            )
        
        if walk_forward_result and walk_forward_result.avg_performance_degradation > 0.3:
            warnings.append(
                f"Significant out-of-sample degradation "
                f"({walk_forward_result.avg_performance_degradation:.1%})"
            )
        
        return warnings


@dataclass
class CandidateScore:
    """Score breakdown for a candidate threshold."""
    total_score: float
    component_scores: Dict[str, float]
    primary_reason: str
    confidence: float


@dataclass
class ThresholdRecommendation:
    """Final threshold recommendation with reasoning."""
    recommended_ev_min: float
    confidence: float  # 0-1
    primary_reason: str
    metrics: ThresholdMetrics
    score_breakdown: CandidateScore
    alternatives: List[float]  # Alternative thresholds to consider
    warnings: List[str]


def generate_recommendation_report(recommendation: ThresholdRecommendation) -> str:
    """Generate a human-readable recommendation report."""
    lines = [
        "=" * 60,
        "EV Threshold Recommendation",
        "=" * 60,
        "",
        f"Recommended EV_Min: {recommendation.recommended_ev_min:.4f}",
        f"Confidence: {recommendation.confidence:.1%}",
        f"Reason: {recommendation.primary_reason}",
        "",
        "Expected Performance:",
        f"  Trades per day: {recommendation.metrics.trades_per_day:.2f}",
        f"  Win rate: {recommendation.metrics.win_rate:.1%}",
        f"  Sharpe ratio: {recommendation.metrics.sharpe_ratio:.3f}",
        f"  Sortino ratio: {recommendation.metrics.sortino_ratio:.3f}",
        f"  Max drawdown: {recommendation.metrics.max_drawdown_bps:.2f} bps",
        f"  Profit factor: {recommendation.metrics.profit_factor:.2f}",
        "",
    ]
    
    if recommendation.alternatives:
        lines.extend([
            "Alternative Thresholds:",
            "  " + ", ".join(f"{t:.4f}" for t in recommendation.alternatives),
            "",
        ])
    
    if recommendation.warnings:
        lines.extend([
            "Warnings:",
        ])
        for warning in recommendation.warnings:
            lines.append(f"  ⚠ {warning}")
        lines.append("")
    
    lines.extend([
        "Score Breakdown:",
    ])
    for component, score in recommendation.score_breakdown.component_scores.items():
        lines.append(f"  {component}: {score:.3f}")
    
    lines.append("=" * 60)
    
    return "\n".join(lines)


# Update exports in __init__.py
__all__ = [
    "EVThresholdSweeper",
    "BacktestTrade",
    "ThresholdMetrics",
    "SweepResult",
    "WalkForwardFold",
    "WalkForwardValidator",
    "WalkForwardFoldResult",
    "WalkForwardValidationResult",
    "KneeDetector",
    "KneeDetectionResult",
    "ThresholdRecommender",
    "CandidateScore",
    "ThresholdRecommendation",
    "generate_sweep_report",
    "generate_walk_forward_report",
    "generate_recommendation_report",
]
