"""
Strategy disable rules shared across routing and candidate generation.

We use env flags to disable:
- specific strategies globally
- mean-reversion strategies for specific symbols

This module exists to avoid architectural disconnects where:
- the ProfileRouter selects a profile, but all strategies under that profile
  are disabled for the symbol; or
- the StrategyRegistry generates a signal for a disabled strategy and relies on
  downstream veto stages to reject it (wasted work, confusing telemetry).
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Set


# Keep aligned with quantgambit.signals.stages.candidate_veto.CandidateVetoConfig.mean_reversion_strategies
MEAN_REVERSION_STRATEGIES: Set[str] = {
    "mean_reversion_fade",
    "poc_magnet_scalp",
    "amt_value_area_rejection_scalp",
    "spread_compression",
    "vwap_reversion",
    "low_vol_grind",
    "liquidity_hunt",
}


def disabled_strategies_from_env(env: Optional[dict] = None) -> Set[str]:
    env = env or os.environ
    raw = env.get("DISABLE_STRATEGIES", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


def disabled_mean_reversion_symbols_from_env(env: Optional[dict] = None) -> Set[str]:
    env = env or os.environ
    raw = env.get("DISABLE_MEAN_REVERSION_SYMBOLS", "")
    return {s.strip().upper() for s in raw.split(",") if s.strip()}


def enabled_strategies_by_symbol_from_env(env: Optional[dict] = None) -> Dict[str, Set[str]]:
    """
    Parse targeted strategy re-enables for symbols blocked by coarse disable rules.

    Format (semicolon separated symbol clauses):
      ENABLE_STRATEGIES_BY_SYMBOL="BTCUSDT:amt_value_area_rejection_scalp|poc_magnet_scalp;SOLUSDT:breakout_continuation"
    """
    env = env or os.environ
    raw = env.get("ENABLE_STRATEGIES_BY_SYMBOL", "")
    parsed: Dict[str, Set[str]] = {}
    if not raw:
        return parsed
    for clause in raw.split(";"):
        token = clause.strip()
        if not token or ":" not in token:
            continue
        symbol_raw, strategies_raw = token.split(":", 1)
        symbol = symbol_raw.strip().upper()
        if not symbol:
            continue
        strategies = {
            s.strip()
            for s in strategies_raw.split("|")
            if s.strip()
        }
        if not strategies:
            continue
        parsed[symbol] = strategies
    return parsed


def is_mean_reversion_strategy(strategy_id: str) -> bool:
    return strategy_id in MEAN_REVERSION_STRATEGIES


def is_strategy_disabled_for_symbol(
    strategy_id: str,
    symbol: Optional[str],
    *,
    disabled_strategies: Optional[Set[str]] = None,
    disabled_mean_rev_symbols: Optional[Set[str]] = None,
    enabled_strategies_by_symbol: Optional[Dict[str, Set[str]]] = None,
) -> bool:
    """
    Returns True if strategy_id is disabled given current env rules for symbol.
    """
    if not strategy_id:
        return True

    disabled_strategies = disabled_strategies or disabled_strategies_from_env()
    if strategy_id in disabled_strategies:
        return True

    if symbol:
        symbol_upper = symbol.upper()
        enabled_strategies_by_symbol = (
            enabled_strategies_by_symbol or enabled_strategies_by_symbol_from_env()
        )
        disabled_mean_rev_symbols = disabled_mean_rev_symbols or disabled_mean_reversion_symbols_from_env()
        if is_mean_reversion_strategy(strategy_id) and symbol_upper in disabled_mean_rev_symbols:
            symbol_overrides = enabled_strategies_by_symbol.get(symbol_upper, set())
            if strategy_id not in symbol_overrides:
                return True

    return False


def enabled_strategies_for_symbol(strategy_ids: Iterable[str], symbol: Optional[str]) -> List[str]:
    """
    Filter strategy IDs to those enabled for the given symbol.

    Note: does not apply session allowlists; that is handled downstream in the
    StrategyRegistry where session is known and enforced.
    """
    disabled_strategies = disabled_strategies_from_env()
    disabled_mean_rev_symbols = disabled_mean_reversion_symbols_from_env()
    enabled_by_symbol = enabled_strategies_by_symbol_from_env()
    enabled: List[str] = []
    for s in strategy_ids:
        s = (s or "").strip()
        if not s:
            continue
        if is_strategy_disabled_for_symbol(
            s,
            symbol,
            disabled_strategies=disabled_strategies,
            disabled_mean_rev_symbols=disabled_mean_rev_symbols,
            enabled_strategies_by_symbol=enabled_by_symbol,
        ):
            continue
        enabled.append(s)
    return enabled
