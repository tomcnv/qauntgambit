"""Unified metrics for live and backtest trading systems.

This module provides the UnifiedMetrics dataclass that ensures consistent
metric computation between live and backtest modes, enabling direct
performance comparison.

Validates: Requirements 9.1, 9.2, 9.4, 9.6
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# Threshold for flagging significant differences (>10%)
SIGNIFICANT_DIFFERENCE_THRESHOLD = 10.0


@dataclass
class UnifiedMetrics:
    """Metrics computed identically for live and backtest.
    
    This dataclass provides a unified representation of trading performance
    metrics that can be computed consistently across both live trading and
    backtesting systems. All metrics use the same calculation methodology
    regardless of the data source.
    
    Attributes:
        # Return metrics
        total_return_pct: Total return as a percentage
        annualized_return_pct: Annualized return as a percentage
        
        # Risk metrics
        sharpe_ratio: Risk-adjusted return (excess return / volatility)
        sortino_ratio: Downside risk-adjusted return (excess return / downside deviation)
        max_drawdown_pct: Maximum peak-to-trough decline as a percentage
        max_drawdown_duration_sec: Duration of the maximum drawdown in seconds
        
        # Trade metrics
        total_trades: Total number of completed trades
        winning_trades: Number of profitable trades
        losing_trades: Number of unprofitable trades
        win_rate: Ratio of winning trades to total trades (0.0 to 1.0)
        profit_factor: Gross profit / gross loss ratio
        avg_trade_pnl: Average profit/loss per trade
        avg_win_pct: Average percentage gain on winning trades
        avg_loss_pct: Average percentage loss on losing trades
        
        # Execution metrics
        avg_slippage_bps: Average slippage in basis points
        avg_latency_ms: Average execution latency in milliseconds
        partial_fill_rate: Rate of partial fills (0.0 to 1.0)
    """
    
    # Return metrics
    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    
    # Risk metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_sec: float = 0.0
    
    # Trade metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_trade_pnl: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    
    # Execution metrics
    avg_slippage_bps: float = 0.0
    avg_latency_ms: float = 0.0
    partial_fill_rate: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for serialization.
        
        Returns:
            Dictionary representation of all metrics.
        """
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedMetrics":
        """Create UnifiedMetrics from dictionary.
        
        Args:
            data: Dictionary containing metric values.
            
        Returns:
            UnifiedMetrics instance with values from dictionary.
        """
        # Filter to only known fields to handle forward compatibility
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered_data)
    
    def is_better_than(
        self,
        other: "UnifiedMetrics",
        primary_metric: str = "sharpe_ratio",
    ) -> bool:
        """Compare if this metrics instance is better than another.
        
        Args:
            other: Another UnifiedMetrics instance to compare against.
            primary_metric: The primary metric to use for comparison.
                Defaults to sharpe_ratio.
                
        Returns:
            True if this instance is better based on the primary metric.
            
        Raises:
            ValueError: If primary_metric is not a valid metric name.
        """
        if not hasattr(self, primary_metric):
            raise ValueError(f"Unknown metric: {primary_metric}")
        
        self_value = getattr(self, primary_metric)
        other_value = getattr(other, primary_metric)
        
        # For most metrics, higher is better
        # Exception: max_drawdown_pct and avg_loss_pct where lower is better
        lower_is_better = {"max_drawdown_pct", "max_drawdown_duration_sec", "avg_loss_pct"}
        
        if primary_metric in lower_is_better:
            return self_value < other_value
        return self_value > other_value
    
    def get_significant_differences(
        self,
        other: "UnifiedMetrics",
        threshold_pct: float = 10.0,
    ) -> Dict[str, Dict[str, Any]]:
        """Find metrics that differ significantly from another instance.
        
        Args:
            other: Another UnifiedMetrics instance to compare against.
            threshold_pct: Percentage difference threshold for significance.
                Defaults to 10%.
                
        Returns:
            Dictionary of significant differences with metric name as key
            and dict containing 'self', 'other', and 'diff_pct' values.
        """
        differences = {}
        
        for field_name in self.__dataclass_fields__:
            self_value = getattr(self, field_name)
            other_value = getattr(other, field_name)
            
            # Skip non-numeric fields
            if not isinstance(self_value, (int, float)):
                continue
            
            # Calculate percentage difference
            if self_value != 0:
                diff_pct = abs((other_value - self_value) / self_value) * 100
            elif other_value != 0:
                diff_pct = 100.0  # 100% difference if self is 0 but other is not
            else:
                diff_pct = 0.0  # Both are 0
            
            if diff_pct > threshold_pct:
                differences[field_name] = {
                    "self": self_value,
                    "other": other_value,
                    "diff_pct": diff_pct,
                }
        
        return differences
    
    def __str__(self) -> str:
        """Return human-readable string representation."""
        return (
            f"UnifiedMetrics(\n"
            f"  Returns: total={self.total_return_pct:.2f}%, annualized={self.annualized_return_pct:.2f}%\n"
            f"  Risk: sharpe={self.sharpe_ratio:.2f}, sortino={self.sortino_ratio:.2f}, "
            f"max_dd={self.max_drawdown_pct:.2f}%\n"
            f"  Trades: total={self.total_trades}, win_rate={self.win_rate:.1%}, "
            f"profit_factor={self.profit_factor:.2f}\n"
            f"  Execution: slippage={self.avg_slippage_bps:.2f}bps, "
            f"latency={self.avg_latency_ms:.1f}ms, partial_fills={self.partial_fill_rate:.1%}\n"
            f")"
        )


def empty_metrics() -> UnifiedMetrics:
    """Create an empty UnifiedMetrics instance with default values.
    
    Returns:
        UnifiedMetrics instance with all values set to defaults (0).
    """
    return UnifiedMetrics()


@dataclass
class MetricsComparison:
    """Result of comparing live vs backtest metrics.
    
    This dataclass holds the complete comparison between live and backtest
    metrics, including significant differences and attribution factors
    that explain the divergence.
    
    Validates: Requirements 9.4, 9.6
    
    Attributes:
        live_metrics: UnifiedMetrics from live trading
        backtest_metrics: UnifiedMetrics from backtesting
        significant_differences: Dict of metrics with >10% difference,
            where each entry contains 'live', 'backtest', 'diff_pct', 'significant'
        divergence_factors: List of identified contributing factors
            explaining the divergence (e.g., "slippage_diff:1.5bps")
        overall_similarity: Float 0-1 indicating how similar the metrics are,
            where 1.0 means identical and 0.0 means completely different
        comparison_timestamp: When the comparison was performed
    """
    
    live_metrics: UnifiedMetrics
    backtest_metrics: UnifiedMetrics
    significant_differences: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    divergence_factors: List[str] = field(default_factory=list)
    overall_similarity: float = 1.0
    comparison_timestamp: datetime = field(default_factory=lambda: datetime.now())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert comparison to dictionary for serialization.
        
        Returns:
            Dictionary representation of the comparison.
        """
        return {
            "live_metrics": self.live_metrics.to_dict(),
            "backtest_metrics": self.backtest_metrics.to_dict(),
            "significant_differences": self.significant_differences,
            "divergence_factors": self.divergence_factors,
            "overall_similarity": self.overall_similarity,
            "comparison_timestamp": self.comparison_timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetricsComparison":
        """Create MetricsComparison from dictionary.
        
        Args:
            data: Dictionary containing comparison data.
            
        Returns:
            MetricsComparison instance.
        """
        return cls(
            live_metrics=UnifiedMetrics.from_dict(data["live_metrics"]),
            backtest_metrics=UnifiedMetrics.from_dict(data["backtest_metrics"]),
            significant_differences=data.get("significant_differences", {}),
            divergence_factors=data.get("divergence_factors", []),
            overall_similarity=data.get("overall_similarity", 1.0),
            comparison_timestamp=datetime.fromisoformat(data["comparison_timestamp"])
            if isinstance(data.get("comparison_timestamp"), str)
            else data.get("comparison_timestamp", datetime.now()),
        )
    
    def has_significant_differences(self) -> bool:
        """Check if there are any significant differences.
        
        Returns:
            True if any metric differs by more than the threshold.
        """
        return len(self.significant_differences) > 0
    
    def get_most_significant_difference(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Get the metric with the largest percentage difference.
        
        Returns:
            Tuple of (metric_name, difference_info) or None if no differences.
        """
        if not self.significant_differences:
            return None
        
        return max(
            self.significant_differences.items(),
            key=lambda x: abs(x[1].get("diff_pct", 0)),
        )
    
    def __str__(self) -> str:
        """Return human-readable string representation."""
        sig_diff_count = len(self.significant_differences)
        factor_count = len(self.divergence_factors)
        return (
            f"MetricsComparison(\n"
            f"  similarity={self.overall_similarity:.1%}\n"
            f"  significant_differences={sig_diff_count}\n"
            f"  divergence_factors={factor_count}: {self.divergence_factors}\n"
            f")"
        )


class MetricsReconciler:
    """Computes and reconciles metrics between live and backtest.
    
    This class ensures that metrics are computed identically for both
    live trading and backtesting systems, enabling direct performance
    comparison. All calculation methodologies are shared between modes.
    
    Validates: Requirements 9.1, 9.2
    
    Attributes:
        _risk_free_rate: Annual risk-free rate for Sharpe/Sortino calculations.
            Defaults to 0.05 (5%).
    """
    
    def __init__(self, risk_free_rate: float = 0.05):
        """Initialize MetricsReconciler.
        
        Args:
            risk_free_rate: Annual risk-free rate for risk-adjusted return
                calculations. Defaults to 0.05 (5%).
        """
        self._risk_free_rate = risk_free_rate
    
    def compute_metrics(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
        initial_equity: Optional[float] = None,
    ) -> UnifiedMetrics:
        """Compute unified metrics from equity curve and trades.
        
        Uses identical calculation methodology for both live and backtest,
        ensuring metrics are directly comparable between modes.
        
        Args:
            equity_curve: List of (timestamp, equity) tuples representing
                the equity value over time. Must be sorted chronologically.
            trades: List of trade dictionaries containing at minimum:
                - pnl: Profit/loss for the trade
                - pnl_pct (optional): Percentage profit/loss
                - slippage_bps (optional): Slippage in basis points
                - latency_ms (optional): Execution latency in milliseconds
                - is_partial (optional): Whether the fill was partial
            initial_equity: Starting equity value. If not provided, uses
                the first equity curve value.
                
        Returns:
            UnifiedMetrics instance with all computed metrics.
        """
        if not equity_curve:
            return empty_metrics()
        
        # Use initial_equity if provided, otherwise use first equity curve value
        start_equity = initial_equity if initial_equity is not None else equity_curve[0][1]
        
        # Calculate returns from equity curve
        returns = self._calculate_returns(equity_curve)
        
        # Calculate total return
        if start_equity > 0:
            total_return = (equity_curve[-1][1] / start_equity - 1) * 100
        else:
            total_return = 0.0
        
        # Calculate duration for annualization
        annualized_return = 0.0
        if len(equity_curve) >= 2:
            duration_seconds = (equity_curve[-1][0] - equity_curve[0][0]).total_seconds()
            duration_days = duration_seconds / 86400
            if duration_days > 0:
                annualized_return = total_return * (365 / duration_days)
        
        # Risk metrics
        sharpe = self._calculate_sharpe(returns)
        sortino = self._calculate_sortino(returns)
        max_dd, max_dd_duration = self._calculate_drawdown(equity_curve)
        
        # Trade metrics
        trade_stats = self._aggregate_trade_stats(trades)
        
        # Execution metrics
        execution_stats = self._aggregate_execution_stats(trades)
        
        return UnifiedMetrics(
            total_return_pct=total_return,
            annualized_return_pct=annualized_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown_pct=max_dd,
            max_drawdown_duration_sec=max_dd_duration,
            total_trades=trade_stats["total_trades"],
            winning_trades=trade_stats["winning_trades"],
            losing_trades=trade_stats["losing_trades"],
            win_rate=trade_stats["win_rate"],
            profit_factor=trade_stats["profit_factor"],
            avg_trade_pnl=trade_stats["avg_trade_pnl"],
            avg_win_pct=trade_stats["avg_win_pct"],
            avg_loss_pct=trade_stats["avg_loss_pct"],
            avg_slippage_bps=execution_stats["avg_slippage_bps"],
            avg_latency_ms=execution_stats["avg_latency_ms"],
            partial_fill_rate=execution_stats["partial_fill_rate"],
        )
    
    def _calculate_returns(
        self,
        equity_curve: List[Tuple[datetime, float]],
    ) -> List[float]:
        """Calculate period-over-period returns from equity curve.
        
        Args:
            equity_curve: List of (timestamp, equity) tuples.
            
        Returns:
            List of decimal returns (e.g., 0.01 for 1% return).
        """
        if len(equity_curve) < 2:
            return []
        
        returns = []
        for i in range(1, len(equity_curve)):
            prev_equity = equity_curve[i - 1][1]
            curr_equity = equity_curve[i][1]
            
            if prev_equity > 0:
                ret = (curr_equity - prev_equity) / prev_equity
                returns.append(ret)
        
        return returns
    
    def _calculate_sharpe(self, returns: List[float]) -> float:
        """Calculate Sharpe ratio from returns.
        
        The Sharpe ratio measures risk-adjusted return as the excess return
        over the risk-free rate divided by the standard deviation of returns.
        
        Args:
            returns: List of decimal returns.
            
        Returns:
            Annualized Sharpe ratio. Returns 0.0 if insufficient data or
            zero volatility.
        """
        if len(returns) < 2:
            return 0.0
        
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = variance ** 0.5
        
        if std_return == 0:
            return 0.0
        
        # Annualize (assuming daily returns)
        annualized_return = mean_return * 252
        annualized_std = std_return * (252 ** 0.5)
        
        return (annualized_return - self._risk_free_rate) / annualized_std
    
    def _calculate_sortino(self, returns: List[float]) -> float:
        """Calculate Sortino ratio from returns.
        
        The Sortino ratio is similar to Sharpe but only considers downside
        deviation (negative returns), providing a better measure of
        downside risk.
        
        Args:
            returns: List of decimal returns.
            
        Returns:
            Annualized Sortino ratio. Returns 0.0 if insufficient data,
            or float('inf') if no downside returns.
        """
        if len(returns) < 2:
            return 0.0
        
        mean_return = sum(returns) / len(returns)
        downside_returns = [r for r in returns if r < 0]
        
        if not downside_returns:
            # No downside returns - infinite Sortino
            return float('inf')
        
        # Calculate downside deviation (semi-deviation)
        downside_variance = sum(r ** 2 for r in downside_returns) / len(downside_returns)
        downside_std = downside_variance ** 0.5
        
        if downside_std == 0:
            return float('inf')
        
        # Annualize (assuming daily returns)
        annualized_return = mean_return * 252
        annualized_downside = downside_std * (252 ** 0.5)
        
        return (annualized_return - self._risk_free_rate) / annualized_downside
    
    def _calculate_drawdown(
        self,
        equity_curve: List[Tuple[datetime, float]],
    ) -> Tuple[float, float]:
        """Calculate maximum drawdown and duration from equity curve.
        
        Drawdown is the peak-to-trough decline during a specific period.
        Maximum drawdown is the largest such decline observed.
        
        Args:
            equity_curve: List of (timestamp, equity) tuples.
            
        Returns:
            Tuple of (max_drawdown_pct, max_drawdown_duration_sec).
            Returns (0.0, 0.0) if insufficient data.
        """
        if len(equity_curve) < 2:
            return 0.0, 0.0
        
        peak = equity_curve[0][1]
        peak_time = equity_curve[0][0]
        max_dd = 0.0
        max_dd_duration = 0.0
        
        for ts, equity in equity_curve:
            if equity > peak:
                # New peak - reset tracking
                peak = equity
                peak_time = ts
            elif peak > 0:
                # Calculate current drawdown
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd
                
                # Calculate duration from peak
                duration = (ts - peak_time).total_seconds()
                if duration > max_dd_duration:
                    max_dd_duration = duration
        
        return max_dd, max_dd_duration
    
    def _aggregate_trade_stats(
        self,
        trades: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Aggregate trade statistics from trade list.
        
        Args:
            trades: List of trade dictionaries with pnl and pnl_pct fields.
            
        Returns:
            Dictionary containing aggregated trade statistics.
        """
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_trade_pnl": 0.0,
                "avg_win_pct": 0.0,
                "avg_loss_pct": 0.0,
            }
        
        winning = [t for t in trades if t.get("pnl", 0) > 0]
        losing = [t for t in trades if t.get("pnl", 0) < 0]
        
        gross_profit = sum(t.get("pnl", 0) for t in winning)
        gross_loss = abs(sum(t.get("pnl", 0) for t in losing))
        
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        
        # Calculate average win/loss percentages
        avg_win_pct = 0.0
        if winning:
            win_pcts = [t.get("pnl_pct", 0) for t in winning]
            avg_win_pct = sum(win_pcts) / len(winning)
        
        avg_loss_pct = 0.0
        if losing:
            loss_pcts = [t.get("pnl_pct", 0) for t in losing]
            avg_loss_pct = sum(loss_pcts) / len(losing)
        
        return {
            "total_trades": len(trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": len(winning) / len(trades),
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float('inf'),
            "avg_trade_pnl": total_pnl / len(trades),
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
        }
    
    def _aggregate_execution_stats(
        self,
        trades: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Aggregate execution statistics from trade list.
        
        Args:
            trades: List of trade dictionaries with slippage_bps, latency_ms,
                and is_partial fields.
            
        Returns:
            Dictionary containing aggregated execution statistics.
        """
        if not trades:
            return {
                "avg_slippage_bps": 0.0,
                "avg_latency_ms": 0.0,
                "partial_fill_rate": 0.0,
            }
        
        total_slippage = sum(t.get("slippage_bps", 0) for t in trades)
        total_latency = sum(t.get("latency_ms", 0) for t in trades)
        partial_count = sum(1 for t in trades if t.get("is_partial", False))
        
        return {
            "avg_slippage_bps": total_slippage / len(trades),
            "avg_latency_ms": total_latency / len(trades),
            "partial_fill_rate": partial_count / len(trades),
        }
    
    def compare_metrics(
        self,
        live_metrics: UnifiedMetrics,
        backtest_metrics: UnifiedMetrics,
        threshold_pct: float = SIGNIFICANT_DIFFERENCE_THRESHOLD,
    ) -> MetricsComparison:
        """Compare live and backtest metrics with attribution.
        
        Compares all metrics between live and backtest, identifies significant
        differences (>10% by default), and attributes the divergence to
        specific factors like execution quality, market conditions, or
        trade selection.
        
        Validates: Requirements 9.4, 9.6
        
        Args:
            live_metrics: UnifiedMetrics from live trading.
            backtest_metrics: UnifiedMetrics from backtesting.
            threshold_pct: Percentage threshold for flagging significant
                differences. Defaults to 10%.
                
        Returns:
            MetricsComparison containing the full comparison results,
            significant differences, and divergence attribution.
        """
        significant_differences: Dict[str, Dict[str, Any]] = {}
        total_diff_score = 0.0
        metric_count = 0
        
        # Compare each metric field
        for field_name in UnifiedMetrics.__dataclass_fields__:
            live_val = getattr(live_metrics, field_name)
            bt_val = getattr(backtest_metrics, field_name)
            
            # Skip non-numeric fields
            if not isinstance(live_val, (int, float)):
                continue
            
            metric_count += 1
            
            # Calculate percentage difference
            if live_val != 0:
                diff_pct = (bt_val - live_val) / abs(live_val) * 100
            elif bt_val != 0:
                diff_pct = 100.0  # 100% difference if live is 0 but backtest is not
            else:
                diff_pct = 0.0  # Both are 0
            
            is_significant = abs(diff_pct) > threshold_pct
            
            # Track for overall similarity calculation
            # Normalize diff to 0-1 range (cap at 100% difference)
            normalized_diff = min(abs(diff_pct) / 100.0, 1.0)
            total_diff_score += normalized_diff
            
            # Only include significant differences in the result
            if is_significant:
                significant_differences[field_name] = {
                    "live": live_val,
                    "backtest": bt_val,
                    "diff_pct": diff_pct,
                    "significant": True,
                }
        
        # Calculate overall similarity (1.0 = identical, 0.0 = completely different)
        if metric_count > 0:
            avg_diff = total_diff_score / metric_count
            overall_similarity = max(0.0, 1.0 - avg_diff)
        else:
            overall_similarity = 1.0
        
        # Attribution analysis - identify factors contributing to divergence
        divergence_factors = self._attribute_divergence(live_metrics, backtest_metrics)
        
        return MetricsComparison(
            live_metrics=live_metrics,
            backtest_metrics=backtest_metrics,
            significant_differences=significant_differences,
            divergence_factors=divergence_factors,
            overall_similarity=overall_similarity,
            comparison_timestamp=datetime.now(),
        )
    
    def _attribute_divergence(
        self,
        live: UnifiedMetrics,
        backtest: UnifiedMetrics,
    ) -> List[str]:
        """Identify factors contributing to live/backtest divergence.
        
        Analyzes the differences between live and backtest metrics to
        identify the primary contributing factors. Factors are categorized
        into:
        - Execution quality (slippage, latency differences)
        - Market conditions (volatility differences via drawdown)
        - Trade selection (win rate, profit factor differences)
        
        Validates: Requirements 9.6
        
        Args:
            live: UnifiedMetrics from live trading.
            backtest: UnifiedMetrics from backtesting.
            
        Returns:
            List of identified divergence factors as descriptive strings.
        """
        factors: List[str] = []
        
        # === Execution Quality Factors ===
        
        # Slippage difference (threshold: 0.5 bps)
        slippage_diff = backtest.avg_slippage_bps - live.avg_slippage_bps
        if abs(slippage_diff) > 0.5:
            direction = "higher" if slippage_diff > 0 else "lower"
            factors.append(f"slippage_diff:{slippage_diff:+.1f}bps (backtest {direction})")
        
        # Latency difference (threshold: 10ms)
        latency_diff = backtest.avg_latency_ms - live.avg_latency_ms
        if abs(latency_diff) > 10.0:
            direction = "higher" if latency_diff > 0 else "lower"
            factors.append(f"latency_diff:{latency_diff:+.1f}ms (backtest {direction})")
        
        # Partial fill rate difference (threshold: 5%)
        partial_diff = backtest.partial_fill_rate - live.partial_fill_rate
        if abs(partial_diff) > 0.05:
            direction = "higher" if partial_diff > 0 else "lower"
            factors.append(f"partial_fill_diff:{partial_diff:+.1%} (backtest {direction})")
        
        # === Market Conditions Factors ===
        
        # Max drawdown difference (threshold: 2%)
        dd_diff = backtest.max_drawdown_pct - live.max_drawdown_pct
        if abs(dd_diff) > 2.0:
            direction = "higher" if dd_diff > 0 else "lower"
            factors.append(f"drawdown_diff:{dd_diff:+.1f}% (backtest {direction})")
        
        # Volatility proxy via Sharpe difference (threshold: 0.2)
        sharpe_diff = backtest.sharpe_ratio - live.sharpe_ratio
        if abs(sharpe_diff) > 0.2:
            direction = "higher" if sharpe_diff > 0 else "lower"
            factors.append(f"sharpe_diff:{sharpe_diff:+.2f} (backtest {direction})")
        
        # === Trade Selection Factors ===
        
        # Win rate difference (threshold: 5%)
        wr_diff = backtest.win_rate - live.win_rate
        if abs(wr_diff) > 0.05:
            direction = "higher" if wr_diff > 0 else "lower"
            factors.append(f"win_rate_diff:{wr_diff:+.1%} (backtest {direction})")
        
        # Profit factor difference (threshold: 0.2)
        # Handle infinity cases
        live_pf = live.profit_factor if live.profit_factor != float('inf') else 10.0
        bt_pf = backtest.profit_factor if backtest.profit_factor != float('inf') else 10.0
        pf_diff = bt_pf - live_pf
        if abs(pf_diff) > 0.2:
            direction = "higher" if pf_diff > 0 else "lower"
            factors.append(f"profit_factor_diff:{pf_diff:+.2f} (backtest {direction})")
        
        # Trade count difference (threshold: 10% of live trades)
        trade_diff = backtest.total_trades - live.total_trades
        if live.total_trades > 0 and abs(trade_diff) > live.total_trades * 0.1:
            direction = "more" if trade_diff > 0 else "fewer"
            factors.append(f"trade_count_diff:{trade_diff:+d} (backtest has {direction})")
        
        # Average trade PnL difference (threshold: 10% of live avg)
        if live.avg_trade_pnl != 0:
            pnl_diff_pct = (backtest.avg_trade_pnl - live.avg_trade_pnl) / abs(live.avg_trade_pnl) * 100
            if abs(pnl_diff_pct) > 10.0:
                direction = "higher" if pnl_diff_pct > 0 else "lower"
                factors.append(f"avg_pnl_diff:{pnl_diff_pct:+.1f}% (backtest {direction})")
        
        # Return metrics difference (threshold: 5%)
        return_diff = backtest.total_return_pct - live.total_return_pct
        if abs(return_diff) > 5.0:
            direction = "higher" if return_diff > 0 else "lower"
            factors.append(f"return_diff:{return_diff:+.1f}% (backtest {direction})")
        
        return factors
