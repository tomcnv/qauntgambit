---
path: /
title: Overview
group: Trading
description: Mission control dashboard with fleet-wide KPIs, equity curve, and execution summary
---

# Overview

The Overview page is the primary landing page for the QuantGambit dashboard. It provides a high-level summary of all trading activity across the fleet.

## Widgets & Cards

### KPI Strip
Top-level metrics: Total PnL, Win Rate, Sharpe Ratio, Max Drawdown, Active Positions, Daily Volume.

### Equity Curve
Interactive time-series chart showing cumulative PnL over time. Supports 1H, 1D, 1W, 1M, ALL ranges.

### Execution Chart
Bar chart of orders placed vs filled vs rejected per time bucket.

### Decision Funnel
Visualizes the pipeline: Events Ingested → Signals Generated → Orders Placed → Fills. Shows rejection reasons at each stage.

### Risk Headroom
Gauge showing current exposure as a percentage of configured risk limits.

### Orders Panel
Recent orders with status indicators (filled, pending, rejected).

### Top Symbols
Ranked list of symbols by PnL contribution.

### Latency Strip
P50/P95/P99 execution latency metrics.

## Modals & Drawers

### Preflight Check
Pre-start validation dialog showing system readiness (data feeds, exchange connectivity, risk limits).

### Alert Detail
Expandable alert cards with severity, timestamp, and recommended action.

## Actions

- Navigate to Live page for real-time monitoring
- Navigate to any sub-page via the sidebar
- Open Command Palette with ⌘K
- Toggle dark/light theme
- Open copilot chat panel

## Settings & Knobs

- Default time range for equity curve
- KPI refresh interval
- Alert severity filter

## Related Pages

- [Live Trading](/live) — Real-time bot monitoring
- [Orders & Fills](/orders) — Detailed order tracking
- [Positions](/positions) — Open position management
