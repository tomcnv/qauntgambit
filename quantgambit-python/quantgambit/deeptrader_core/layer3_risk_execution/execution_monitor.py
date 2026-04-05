"""
Execution Monitor - Monitor execution quality

Tracks:
1. Slippage (actual vs expected price)
2. Fill rate (filled vs submitted orders)
3. Execution latency (time to fill)
4. Rejection rate (rejected orders)
5. Partial fills

Returns execution quality metrics.
"""

from typing import Dict, List
from collections import deque
import time


class ExecutionMonitor:
    """Monitor execution quality"""
    
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        
        # Execution history
        self.slippages = deque(maxlen=window_size)
        self.execution_times = deque(maxlen=window_size)
        self.fill_statuses = deque(maxlen=window_size)
        
        # Stats
        self.total_orders = 0
        self.total_filled = 0
        self.total_rejected = 0
        self.total_slippage_bps = 0.0
        self.total_execution_time_ms = 0.0
    
    def record_execution(
        self,
        filled: bool,
        slippage_bps: float = 0.0,
        execution_time_ms: float = 0.0,
        rejected: bool = False
    ):
        """
        Record an execution
        
        Args:
            filled: Whether order was filled
            slippage_bps: Slippage in basis points
            execution_time_ms: Execution time in milliseconds
            rejected: Whether order was rejected
        """
        self.total_orders += 1
        
        if filled:
            self.total_filled += 1
            self.slippages.append(slippage_bps)
            self.execution_times.append(execution_time_ms)
            self.fill_statuses.append(True)
            self.total_slippage_bps += slippage_bps
            self.total_execution_time_ms += execution_time_ms
        elif rejected:
            self.total_rejected += 1
            self.fill_statuses.append(False)
        else:
            self.fill_statuses.append(False)
    
    def get_stats(self) -> Dict:
        """Get execution quality statistics"""
        # Recent stats (last N orders)
        recent_fill_rate = (sum(self.fill_statuses) / len(self.fill_statuses) * 100) if self.fill_statuses else 0.0
        recent_avg_slippage = (sum(self.slippages) / len(self.slippages)) if self.slippages else 0.0
        recent_avg_execution_time = (sum(self.execution_times) / len(self.execution_times)) if self.execution_times else 0.0
        
        # Overall stats
        overall_fill_rate = (self.total_filled / self.total_orders * 100) if self.total_orders > 0 else 0.0
        overall_rejection_rate = (self.total_rejected / self.total_orders * 100) if self.total_orders > 0 else 0.0
        overall_avg_slippage = (self.total_slippage_bps / self.total_filled) if self.total_filled > 0 else 0.0
        overall_avg_execution_time = (self.total_execution_time_ms / self.total_filled) if self.total_filled > 0 else 0.0
        
        return {
            'recent': {
                'fill_rate': recent_fill_rate,
                'avg_slippage_bps': recent_avg_slippage,
                'avg_execution_time_ms': recent_avg_execution_time,
                'sample_size': len(self.fill_statuses),
            },
            'overall': {
                'total_orders': self.total_orders,
                'total_filled': self.total_filled,
                'total_rejected': self.total_rejected,
                'fill_rate': overall_fill_rate,
                'rejection_rate': overall_rejection_rate,
                'avg_slippage_bps': overall_avg_slippage,
                'avg_execution_time_ms': overall_avg_execution_time,
            }
        }
    
    def get_quality_score(self) -> float:
        """
        Calculate execution quality score (0.0-1.0)
        
        Based on:
        - Fill rate (40%)
        - Low slippage (30%)
        - Fast execution (20%)
        - Low rejection rate (10%)
        """
        stats = self.get_stats()
        overall = stats['overall']
        
        # Fill rate score (0-1)
        fill_rate_score = overall['fill_rate'] / 100.0
        
        # Slippage score (0-1, lower is better)
        # Assume 5 bps is acceptable, 0 bps is perfect
        slippage_score = max(0.0, 1.0 - (overall['avg_slippage_bps'] / 5.0))
        
        # Execution time score (0-1, lower is better)
        # Assume 100ms is acceptable, 0ms is perfect
        execution_time_score = max(0.0, 1.0 - (overall['avg_execution_time_ms'] / 100.0))
        
        # Rejection rate score (0-1, lower is better)
        rejection_rate_score = 1.0 - (overall['rejection_rate'] / 100.0)
        
        # Weighted average
        quality_score = (
            0.4 * fill_rate_score +
            0.3 * slippage_score +
            0.2 * execution_time_score +
            0.1 * rejection_rate_score
        )
        
        return min(1.0, max(0.0, quality_score))























