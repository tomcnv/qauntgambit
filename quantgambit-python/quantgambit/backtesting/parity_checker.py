"""Backtest/Live Parity Checker.

Feature: strategy-signal-architecture-fixes
Requirement 10: Backtest/Live Parity Guarantees

This module provides the ParityChecker class that ensures backtest and live
systems use identical logic and configuration. It compares critical configuration
values between backtest and live modes to guarantee that backtest results are
predictive of live performance.

Acceptance Criteria:
- 10.1: System SHALL use IDENTICAL stage implementations for backtest and live modes
- 10.2: System SHALL use IDENTICAL threshold calculations for backtest and live modes
- 10.3: System SHALL use IDENTICAL candidate generation logic for backtest and live modes
- 10.4: WHEN running backtest THEN System SHALL use the SAME fee model as live (not simplified)
- 10.5: WHEN running backtest THEN System SHALL use the SAME slippage model as live (not zero slippage)
- 10.6: Backtest_Executor SHALL accept `parity_mode: bool = True` that enforces parity
- 10.7: WHEN parity_mode is True AND any config differs from live THEN System SHALL raise ConfigurationError
- 10.8: System SHALL provide `compare_configs(backtest_config, live_config) -> list[str]`
- 10.9: System SHALL log a parity check summary at backtest start
- 10.10: Backtest results SHALL include `parity_verified: bool` field
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from quantgambit.observability.logger import log_info, log_warning


@dataclass
class ParityCheckResult:
    """Result of backtest/live parity check.
    
    Attributes:
        parity_verified: True if all critical configs match between backtest and live
        differences: List of config differences found (format: "key: backtest=X, live=Y")
        warnings: List of non-critical warnings (e.g., missing optional configs)
    """
    parity_verified: bool
    differences: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def __str__(self) -> str:
        """Human-readable summary of parity check result."""
        if self.parity_verified:
            return "Parity verified: All critical configs match"
        else:
            diff_summary = "; ".join(self.differences[:3])
            if len(self.differences) > 3:
                diff_summary += f" (and {len(self.differences) - 3} more)"
            return f"Parity FAILED: {diff_summary}"


class ParityChecker:
    """Ensures backtest and live systems use identical logic.
    
    This class compares critical configuration values between backtest and live
    modes to guarantee that backtest results are predictive of live performance.
    
    The CRITICAL_CONFIGS list defines which configuration keys must match exactly
    between backtest and live modes. These include:
    - EV gate thresholds (ev_min, ev_min_floor)
    - Threshold calculator parameters (k, b, floor_bps)
    - Fee model parameters (maker_fee_bps, taker_fee_bps)
    - Slippage model parameters (base_slippage_bps)
    
    Example usage:
        checker = ParityChecker()
        result = checker.compare_configs(backtest_config, live_config)
        
        if not result.parity_verified:
            raise ConfigurationError(f"Parity check failed: {result.differences}")
    """
    
    # Critical configuration keys that MUST match between backtest and live
    # These are dot-separated paths for nested config access
    CRITICAL_CONFIGS: List[str] = [
        "ev_gate.ev_min",
        "ev_gate.ev_min_floor",
        "threshold_calculator.k",
        "threshold_calculator.b",
        "threshold_calculator.floor_bps",
        "fee_model.maker_fee_bps",
        "fee_model.taker_fee_bps",
        "slippage_model.base_slippage_bps",
    ]
    
    # Additional configs to check for warnings (non-critical)
    WARNING_CONFIGS: List[str] = [
        "fee_model.model_type",
        "slippage_model.model_type",
    ]
    
    def compare_configs(
        self,
        backtest_config: Dict[str, Any],
        live_config: Dict[str, Any],
    ) -> ParityCheckResult:
        """Compare backtest and live configs for parity.
        
        Checks all CRITICAL_CONFIGS for exact matches between backtest and live
        configurations. Also checks pipeline_stages ordering and generates
        warnings for non-critical config differences.
        
        Args:
            backtest_config: Configuration dictionary for backtest mode
            live_config: Configuration dictionary for live mode
            
        Returns:
            ParityCheckResult with parity_verified status, differences, and warnings
        """
        differences: List[str] = []
        warnings: List[str] = []
        
        # Check critical configs
        for key in self.CRITICAL_CONFIGS:
            bt_value = self._get_nested(backtest_config, key)
            live_value = self._get_nested(live_config, key)
            
            if bt_value != live_value:
                differences.append(
                    f"{key}: backtest={bt_value}, live={live_value}"
                )
        
        # Check stage ordering (critical)
        bt_stages = backtest_config.get("pipeline_stages", [])
        live_stages = live_config.get("pipeline_stages", [])
        if bt_stages != live_stages:
            differences.append(
                f"pipeline_stages: backtest={bt_stages}, live={live_stages}"
            )
        
        # Check warning configs (non-critical)
        for key in self.WARNING_CONFIGS:
            bt_value = self._get_nested(backtest_config, key)
            live_value = self._get_nested(live_config, key)
            
            if bt_value != live_value:
                warnings.append(
                    f"{key}: backtest={bt_value}, live={live_value}"
                )
        
        # Check for simplified fee model (warning)
        fee_model_type = self._get_nested(backtest_config, "fee_model.model_type")
        if fee_model_type == "simplified" or fee_model_type == "zero":
            warnings.append(
                f"fee_model.model_type={fee_model_type} may not match live behavior"
            )
        
        # Check for zero slippage (warning)
        slippage_bps = self._get_nested(backtest_config, "slippage_model.base_slippage_bps")
        if slippage_bps == 0 or slippage_bps is None:
            warnings.append(
                "slippage_model.base_slippage_bps=0 may not match live behavior"
            )
        
        return ParityCheckResult(
            parity_verified=len(differences) == 0,
            differences=differences,
            warnings=warnings,
        )
    
    def _get_nested(self, config: Dict[str, Any], key: str) -> Any:
        """Get nested config value by dot-separated key.
        
        Args:
            config: Configuration dictionary
            key: Dot-separated key path (e.g., "ev_gate.ev_min")
            
        Returns:
            The value at the nested path, or None if not found
        """
        parts = key.split(".")
        value = config
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value
    
    def verify_stage_implementations(
        self,
        backtest_stages: List[str],
        live_stages: List[str],
    ) -> ParityCheckResult:
        """Verify that backtest and live use the same stage implementations.
        
        This method checks that the stage class names match between backtest
        and live modes, ensuring identical pipeline behavior.
        
        Args:
            backtest_stages: List of stage class names for backtest
            live_stages: List of stage class names for live
            
        Returns:
            ParityCheckResult with verification status
        """
        differences: List[str] = []
        warnings: List[str] = []
        
        if len(backtest_stages) != len(live_stages):
            differences.append(
                f"stage_count: backtest={len(backtest_stages)}, live={len(live_stages)}"
            )
        
        # Check each stage
        for i, (bt_stage, live_stage) in enumerate(zip(backtest_stages, live_stages)):
            if bt_stage != live_stage:
                differences.append(
                    f"stage[{i}]: backtest={bt_stage}, live={live_stage}"
                )
        
        # Check for extra stages in either list
        if len(backtest_stages) > len(live_stages):
            extra = backtest_stages[len(live_stages):]
            differences.append(f"extra_backtest_stages: {extra}")
        elif len(live_stages) > len(backtest_stages):
            extra = live_stages[len(backtest_stages):]
            differences.append(f"extra_live_stages: {extra}")
        
        return ParityCheckResult(
            parity_verified=len(differences) == 0,
            differences=differences,
            warnings=warnings,
        )
    
    def verify_fee_model(
        self,
        backtest_config: Dict[str, Any],
        live_config: Dict[str, Any],
    ) -> ParityCheckResult:
        """Verify that backtest uses the same fee model as live (not simplified).
        
        Args:
            backtest_config: Backtest fee model configuration
            live_config: Live fee model configuration
            
        Returns:
            ParityCheckResult with verification status
        """
        differences: List[str] = []
        warnings: List[str] = []
        
        # Check fee model type
        bt_model = backtest_config.get("model_type", "flat")
        live_model = live_config.get("model_type", "flat")
        
        if bt_model != live_model:
            differences.append(f"fee_model.model_type: backtest={bt_model}, live={live_model}")
        
        # Check for simplified/zero fee model
        if bt_model in ("simplified", "zero"):
            differences.append(
                f"fee_model.model_type={bt_model} is not allowed in parity mode"
            )
        
        # Check fee values
        bt_maker = backtest_config.get("maker_fee_bps")
        live_maker = live_config.get("maker_fee_bps")
        if bt_maker != live_maker:
            differences.append(f"fee_model.maker_fee_bps: backtest={bt_maker}, live={live_maker}")
        
        bt_taker = backtest_config.get("taker_fee_bps")
        live_taker = live_config.get("taker_fee_bps")
        if bt_taker != live_taker:
            differences.append(f"fee_model.taker_fee_bps: backtest={bt_taker}, live={live_taker}")
        
        return ParityCheckResult(
            parity_verified=len(differences) == 0,
            differences=differences,
            warnings=warnings,
        )
    
    def verify_slippage_model(
        self,
        backtest_config: Dict[str, Any],
        live_config: Dict[str, Any],
    ) -> ParityCheckResult:
        """Verify that backtest uses the same slippage model as live (not zero).
        
        Args:
            backtest_config: Backtest slippage model configuration
            live_config: Live slippage model configuration
            
        Returns:
            ParityCheckResult with verification status
        """
        differences: List[str] = []
        warnings: List[str] = []
        
        # Check slippage model type
        bt_model = backtest_config.get("model_type", "flat")
        live_model = live_config.get("model_type", "flat")
        
        if bt_model != live_model:
            differences.append(f"slippage_model.model_type: backtest={bt_model}, live={live_model}")
        
        # Check for zero slippage
        bt_slippage = backtest_config.get("base_slippage_bps", 0)
        live_slippage = live_config.get("base_slippage_bps", 0)
        
        if bt_slippage == 0 and live_slippage > 0:
            differences.append(
                f"slippage_model.base_slippage_bps: backtest=0 (zero slippage not allowed in parity mode)"
            )
        elif bt_slippage != live_slippage:
            differences.append(
                f"slippage_model.base_slippage_bps: backtest={bt_slippage}, live={live_slippage}"
            )
        
        return ParityCheckResult(
            parity_verified=len(differences) == 0,
            differences=differences,
            warnings=warnings,
        )
    
    def log_parity_summary(
        self,
        result: ParityCheckResult,
        run_id: Optional[str] = None,
    ) -> None:
        """Log a summary of the parity check result.
        
        Args:
            result: The parity check result to log
            run_id: Optional run ID for context
        """
        if result.parity_verified:
            log_info(
                "parity_check_passed",
                run_id=run_id,
                critical_configs_checked=len(self.CRITICAL_CONFIGS),
                warnings_count=len(result.warnings),
            )
        else:
            log_warning(
                "parity_check_failed",
                run_id=run_id,
                differences_count=len(result.differences),
                differences=result.differences[:5],  # Log first 5 differences
                warnings_count=len(result.warnings),
            )
        
        # Log warnings separately
        for warning in result.warnings:
            log_warning(
                "parity_check_warning",
                run_id=run_id,
                warning=warning,
            )
