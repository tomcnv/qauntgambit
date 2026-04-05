"""
Deterministic simulation harness for QuantGambit.

This package provides:
- SimClock: Deterministic time for tests and replay
- SimExchange: In-process simulated exchange
- Scenario builders for integration tests

The simulation harness enables:
- Deterministic test execution (no timing flakiness)
- Fast replay (no real waiting)
- Reproducible scenarios
- Integration testing without testnet
"""

from quantgambit.core.clock import SimClock  # Re-export from core
from quantgambit.sim.sim_exchange import SimExchange, SimExchangeConfig
from quantgambit.sim.scenarios import (
    ScenarioBuilder,
    bracket_success_scenario,
    bracket_tp_reject_scenario,
    partial_fill_scenario,
    ws_disconnect_scenario,
)

__all__ = [
    "SimClock",
    "SimExchange",
    "SimExchangeConfig",
    "ScenarioBuilder",
    "bracket_success_scenario",
    "bracket_tp_reject_scenario",
    "partial_fill_scenario",
    "ws_disconnect_scenario",
]
