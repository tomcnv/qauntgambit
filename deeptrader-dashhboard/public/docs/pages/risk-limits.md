---
path: /risk/limits
title: Limits & Guardrails
group: Risk
description: Live risk controls including position limits, exposure caps, and circuit breakers
---

# Limits & Guardrails

Configure and monitor all risk limits and guardrails that protect the trading fleet.

## Widgets & Cards

### Max Daily Loss
Configurable daily loss limit (USD and %). Shows current usage and remaining headroom.

### Max Exposure
Total portfolio exposure cap. Displays current vs allowed exposure.

### Position Limits
Per-symbol and total position count limits.

### Circuit Breaker
Auto-halt trigger: loss threshold, cooldown period, current status (armed/tripped/cooldown).

### Leverage Limits
Max leverage per symbol and portfolio-wide. Shows current effective leverage.

## Actions

- Edit any risk limit value
- Enable/disable circuit breaker
- Reset circuit breaker cooldown
- View limit breach history
- Export current limits as JSON

## Settings & Knobs

- Max daily loss (USD and %)
- Max total exposure (%)
- Max single position size (%)
- Max per-symbol exposure (%)
- Max leverage
- Max concurrent positions
- Circuit breaker loss threshold
- Circuit breaker cooldown minutes
- Allowed environments (paper/live)
- Allowed exchanges

## Related Pages

- [Risk Exposure](/risk/exposure) — Historical exposure data
- [VaR & Stress Tests](/risk/metrics) — Risk analytics
- [Incidents](/risk/incidents) — Breach history
