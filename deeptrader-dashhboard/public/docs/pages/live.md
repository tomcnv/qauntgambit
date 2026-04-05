---
path: /live
title: Live Trading
group: Trading
description: Real-time bot monitoring with kill switch, ops KPIs, and live order tape
---

# Live Trading

The Live Trading page provides real-time monitoring of active trading bots with controls for immediate intervention.

## Widgets & Cards

### Status Strip
Bot state indicator: Running, Paused, Halted, Error. Shows uptime and last heartbeat age.

### Kill Switch
Emergency stop button that flattens all positions and cancels pending orders. Requires confirmation in live mode.

### Ops KPIs
Real-time metrics: Decisions/sec, Fill Rate, Avg Latency, Active Positions, Unrealized PnL.

### Symbol Strip
Horizontal scrollable list of actively traded symbols with mini sparklines.

### Why-No-Trades Panel
Diagnostic panel explaining why the bot isn't trading: data quality issues, risk limits hit, no signals, warmup incomplete.

### Loss Prevention
Daily loss tracking with circuit breaker status and cooldown timer.

### Rejected Signals
Stream of recently rejected signals with rejection reasons and symbol context.

### Order Attempts
Timeline of order submission attempts with fill/reject outcomes.

### Blocking Intents
List of pending intents that are blocked by risk checks or rate limits.

### Live Tape
Real-time scrolling feed of all events: decisions, orders, fills, guardrail triggers.

## Modals & Drawers

### Replace Order Dialog
Form to modify an existing pending order (price, size). Shows current vs new parameters.

### Trade Inspector
Slide-over drawer showing full trade lifecycle: signal → decision → order → fill → PnL attribution.

## Actions

- Start/Pause/Halt bot via control buttons
- Emergency flatten all positions
- Replace a pending order
- Inspect any trade in the tape
- Filter tape by event type or symbol

## Settings & Knobs

- Tape scroll speed and buffer size
- Auto-refresh interval
- Symbol filter for focused monitoring

## Related Pages

- [Overview](/) — Fleet-wide summary
- [Orders & Fills](/orders) — Detailed order tracking
- [Pipeline Health](/pipeline-health) — Engine internals
