"""Configuration diff engine for trading pipeline integration.

This module provides configuration comparison functionality to identify
differences between live and backtest configurations with severity categorization.

Feature: trading-pipeline-integration
Requirements: 1.3 - WHEN configuration differs between backtest and live THEN the System
              SHALL log all differences with severity levels (critical, warning, info)
              1.4 - THE System SHALL provide a configuration diff report showing all
              parameter differences before backtest execution
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from quantgambit.integration.config_version import ConfigVersion


# Critical parameters that significantly impact trading behavior and P&L
# Changes to these require explicit acknowledgment before proceeding
CRITICAL_PARAMS: List[str] = [
    # Fee and cost parameters
    "fee_rate",
    "maker_fee_rate",
    "taker_fee_rate",
    "fee_bps",
    
    # Slippage parameters
    "slippage_bps",
    "slippage_pct",
    "max_slippage_bps",
    
    # Position sizing parameters
    "position_size_pct",
    "max_position_size",
    "max_positions",
    "max_position_value",
    
    # Leverage parameters
    "leverage",
    "max_leverage",
    
    # Entry/exit thresholds
    "entry_threshold",
    "exit_threshold",
    "entry_threshold_bps",
    "exit_threshold_bps",
    
    # Risk management parameters
    "stop_loss_pct",
    "stop_loss_bps",
    "take_profit_pct",
    "take_profit_bps",
    "max_drawdown_pct",
    
    # EV gate parameters
    "ev_threshold",
    "min_ev",
    "ev_gate_threshold",
]

# Warning parameters that may affect trading behavior but are less critical
# Changes to these are logged but don't require acknowledgment
WARNING_PARAMS: List[str] = [
    # Timing parameters
    "cooldown_sec",
    "cooldown_ms",
    "min_hold_time_sec",
    "max_hold_time_sec",
    
    # Volume/liquidity parameters
    "min_volume",
    "min_volume_usd",
    "min_liquidity",
    
    # Spread parameters
    "min_spread_bps",
    "max_spread_bps",
    
    # AMT parameters
    "amt_lookback_periods",
    "amt_percentile",
    
    # Profile router parameters
    "profile_hysteresis_threshold",
    "profile_stability_window",
    
    # Volatility parameters
    "vol_shock_threshold",
    "vol_lookback_periods",
    
    # Confirmation parameters
    "confirmation_window_sec",
    "min_confirmation_score",
]


@dataclass
class ConfigDiff:
    """Difference between two configurations.
    
    Represents the categorized differences between a source and target
    configuration version. Differences are categorized by severity:
    - critical_diffs: Parameters that significantly impact trading behavior
    - warning_diffs: Parameters that may affect behavior but are less critical
    - info_diffs: All other parameter differences
    
    Feature: trading-pipeline-integration
    Requirements: 1.3, 1.4
    
    Attributes:
        source_version: Version ID of the source configuration
        target_version: Version ID of the target configuration
        critical_diffs: List of (key, old_value, new_value) for critical parameters
        warning_diffs: List of (key, old_value, new_value) for warning parameters
        info_diffs: List of (key, old_value, new_value) for info parameters
    """
    source_version: str
    target_version: str
    critical_diffs: List[Tuple[str, Any, Any]] = field(default_factory=list)
    warning_diffs: List[Tuple[str, Any, Any]] = field(default_factory=list)
    info_diffs: List[Tuple[str, Any, Any]] = field(default_factory=list)
    
    @property
    def has_critical_diffs(self) -> bool:
        """Check if there are any critical differences."""
        return len(self.critical_diffs) > 0
    
    @property
    def has_any_diffs(self) -> bool:
        """Check if there are any differences at all."""
        return (
            len(self.critical_diffs) > 0 or
            len(self.warning_diffs) > 0 or
            len(self.info_diffs) > 0
        )
    
    @property
    def total_diffs(self) -> int:
        """Get total number of differences."""
        return (
            len(self.critical_diffs) +
            len(self.warning_diffs) +
            len(self.info_diffs)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation of the ConfigDiff
        """
        return {
            "source_version": self.source_version,
            "target_version": self.target_version,
            "critical_diffs": [
                {"key": k, "old": o, "new": n}
                for k, o, n in self.critical_diffs
            ],
            "warning_diffs": [
                {"key": k, "old": o, "new": n}
                for k, o, n in self.warning_diffs
            ],
            "info_diffs": [
                {"key": k, "old": o, "new": n}
                for k, o, n in self.info_diffs
            ],
            "has_critical_diffs": self.has_critical_diffs,
            "total_diffs": self.total_diffs,
        }
    
    def format_report(self) -> str:
        """Format a human-readable diff report.
        
        Returns:
            Formatted string report of all differences
        """
        lines = [
            f"Configuration Diff Report",
            f"Source: {self.source_version}",
            f"Target: {self.target_version}",
            f"Total differences: {self.total_diffs}",
            "",
        ]
        
        if self.critical_diffs:
            lines.append("CRITICAL DIFFERENCES (require acknowledgment):")
            for key, old, new in self.critical_diffs:
                lines.append(f"  - {key}: {old!r} -> {new!r}")
            lines.append("")
        
        if self.warning_diffs:
            lines.append("WARNING DIFFERENCES (may affect behavior):")
            for key, old, new in self.warning_diffs:
                lines.append(f"  - {key}: {old!r} -> {new!r}")
            lines.append("")
        
        if self.info_diffs:
            lines.append("INFO DIFFERENCES (informational):")
            for key, old, new in self.info_diffs:
                lines.append(f"  - {key}: {old!r} -> {new!r}")
            lines.append("")
        
        if not self.has_any_diffs:
            lines.append("No differences found.")
        
        return "\n".join(lines)


class ConfigDiffEngine:
    """Engine for comparing configuration versions.
    
    Compares two ConfigVersion objects and categorizes all parameter
    differences by severity level (critical, warning, info).
    
    Feature: trading-pipeline-integration
    Requirements: 1.3, 1.4
    
    Example:
        >>> engine = ConfigDiffEngine()
        >>> diff = engine.compare(live_config, backtest_config)
        >>> if diff.has_critical_diffs:
        ...     print("Critical differences found!")
        ...     print(diff.format_report())
    """
    
    def __init__(
        self,
        critical_params: List[str] | None = None,
        warning_params: List[str] | None = None,
    ) -> None:
        """Initialize the ConfigDiffEngine.
        
        Args:
            critical_params: Custom list of critical parameter names.
                            Defaults to CRITICAL_PARAMS if not provided.
            warning_params: Custom list of warning parameter names.
                           Defaults to WARNING_PARAMS if not provided.
        """
        self._critical_params = set(critical_params or CRITICAL_PARAMS)
        self._warning_params = set(warning_params or WARNING_PARAMS)
    
    def compare(
        self,
        source: ConfigVersion,
        target: ConfigVersion,
    ) -> ConfigDiff:
        """Compare two configuration versions and categorize differences.
        
        Identifies all parameter differences between source and target
        configurations and categorizes them as critical, warning, or info
        based on the parameter's impact on trading behavior.
        
        Feature: trading-pipeline-integration
        Requirements: 1.3, 1.4
        
        Args:
            source: The source configuration (typically live config)
            target: The target configuration (typically backtest config)
            
        Returns:
            ConfigDiff with all differences categorized by severity
        """
        critical_diffs: List[Tuple[str, Any, Any]] = []
        warning_diffs: List[Tuple[str, Any, Any]] = []
        info_diffs: List[Tuple[str, Any, Any]] = []
        
        # Get all unique keys from both configurations
        all_keys = set(source.parameters.keys()) | set(target.parameters.keys())
        
        for key in sorted(all_keys):
            source_value = source.parameters.get(key)
            target_value = target.parameters.get(key)
            
            # Check if values differ
            if not self._values_equal(source_value, target_value):
                diff_tuple = (key, source_value, target_value)
                
                # Categorize the difference
                if self._is_critical_param(key):
                    critical_diffs.append(diff_tuple)
                elif self._is_warning_param(key):
                    warning_diffs.append(diff_tuple)
                else:
                    info_diffs.append(diff_tuple)
        
        return ConfigDiff(
            source_version=source.version_id,
            target_version=target.version_id,
            critical_diffs=critical_diffs,
            warning_diffs=warning_diffs,
            info_diffs=info_diffs,
        )
    
    def compare_dicts(
        self,
        source_params: Dict[str, Any],
        target_params: Dict[str, Any],
        source_version: str = "source",
        target_version: str = "target",
    ) -> ConfigDiff:
        """Compare two parameter dictionaries directly.
        
        Convenience method for comparing raw parameter dictionaries
        without requiring full ConfigVersion objects.
        
        Args:
            source_params: Source parameter dictionary
            target_params: Target parameter dictionary
            source_version: Label for source version
            target_version: Label for target version
            
        Returns:
            ConfigDiff with all differences categorized by severity
        """
        critical_diffs: List[Tuple[str, Any, Any]] = []
        warning_diffs: List[Tuple[str, Any, Any]] = []
        info_diffs: List[Tuple[str, Any, Any]] = []
        
        # Get all unique keys from both dictionaries
        all_keys = set(source_params.keys()) | set(target_params.keys())
        
        for key in sorted(all_keys):
            source_value = source_params.get(key)
            target_value = target_params.get(key)
            
            # Check if values differ
            if not self._values_equal(source_value, target_value):
                diff_tuple = (key, source_value, target_value)
                
                # Categorize the difference
                if self._is_critical_param(key):
                    critical_diffs.append(diff_tuple)
                elif self._is_warning_param(key):
                    warning_diffs.append(diff_tuple)
                else:
                    info_diffs.append(diff_tuple)
        
        return ConfigDiff(
            source_version=source_version,
            target_version=target_version,
            critical_diffs=critical_diffs,
            warning_diffs=warning_diffs,
            info_diffs=info_diffs,
        )
    
    def _is_critical_param(self, key: str) -> bool:
        """Check if a parameter key is critical.
        
        Args:
            key: Parameter key to check
            
        Returns:
            True if the parameter is critical
        """
        # Check exact match
        if key in self._critical_params:
            return True
        
        # Check if key ends with a critical suffix (for nested params)
        # e.g., "strategy.fee_rate" should match "fee_rate"
        key_parts = key.split(".")
        if key_parts[-1] in self._critical_params:
            return True
        
        return False
    
    def _is_warning_param(self, key: str) -> bool:
        """Check if a parameter key is a warning-level parameter.
        
        Args:
            key: Parameter key to check
            
        Returns:
            True if the parameter is warning-level
        """
        # Check exact match
        if key in self._warning_params:
            return True
        
        # Check if key ends with a warning suffix (for nested params)
        key_parts = key.split(".")
        if key_parts[-1] in self._warning_params:
            return True
        
        return False
    
    def _values_equal(self, a: Any, b: Any) -> bool:
        """Check if two values are equal, handling special cases.
        
        Handles floating point comparison with tolerance and
        None vs missing key distinction.
        
        Args:
            a: First value
            b: Second value
            
        Returns:
            True if values are considered equal
        """
        # Handle None cases
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        
        # Handle float comparison with tolerance
        if isinstance(a, float) and isinstance(b, float):
            # Use relative tolerance for larger values, absolute for small
            if abs(a) < 1e-9 and abs(b) < 1e-9:
                return True
            rel_tol = 1e-9
            return abs(a - b) <= rel_tol * max(abs(a), abs(b))
        
        # Handle int/float comparison
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(a) == float(b)
        
        # Handle dict comparison recursively
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a.keys()) != set(b.keys()):
                return False
            return all(self._values_equal(a[k], b[k]) for k in a.keys())
        
        # Handle list comparison
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                return False
            return all(self._values_equal(x, y) for x, y in zip(a, b))
        
        # Default equality check
        return a == b
    
    def add_critical_param(self, param: str) -> None:
        """Add a parameter to the critical list.
        
        Args:
            param: Parameter name to add
        """
        self._critical_params.add(param)
    
    def add_warning_param(self, param: str) -> None:
        """Add a parameter to the warning list.
        
        Args:
            param: Parameter name to add
        """
        self._warning_params.add(param)
    
    def remove_critical_param(self, param: str) -> None:
        """Remove a parameter from the critical list.
        
        Args:
            param: Parameter name to remove
        """
        self._critical_params.discard(param)
    
    def remove_warning_param(self, param: str) -> None:
        """Remove a parameter from the warning list.
        
        Args:
            param: Parameter name to remove
        """
        self._warning_params.discard(param)
