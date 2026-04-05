---
path: /risk/metrics
title: VaR & Stress Tests
group: Risk
description: Value-at-Risk trends, expected shortfall, and scenario-based stress testing
---

# VaR & Stress Tests

Quantitative risk analytics including VaR, Expected Shortfall, and custom scenario stress tests.

## Widgets & Cards

### Summary KPIs
Current VaR (95%), VaR (99%), Expected Shortfall, Max Drawdown, Sharpe Ratio.

### VaR Trend
Time-series chart of daily VaR estimates with actual P&L overlay.

### Exposure Snapshot
Current portfolio exposure breakdown for VaR context.

### Risk Events
Timeline of risk limit breaches, circuit breaker triggers, and guardrail activations.

## Modals & Drawers

### VaR Config
Configure VaR calculation parameters: confidence level, lookback window, method (historical/parametric/Monte Carlo).

### Scenario Builder
Create custom stress scenarios: define market shocks per symbol, correlation assumptions, and time horizon.

### Scenario Results
Display stress test outcomes: portfolio P&L impact, worst-case positions, margin impact.

## Actions

- Run a new stress test scenario
- Compare scenarios side-by-side
- Export VaR report
- Configure VaR parameters
- View historical risk events

## Settings & Knobs

- VaR confidence level (95%, 99%)
- VaR lookback window (days)
- VaR calculation method
- Stress test correlation assumptions

## Related Pages

- [Limits & Guardrails](/risk/limits) — Risk controls
- [Exposure](/risk/exposure) — Exposure analysis
- [Incidents](/risk/incidents) — Breach history
