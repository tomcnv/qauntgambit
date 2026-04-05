---
path: /signals
title: Signals
group: Analysis
description: Signal pipeline monitoring with feature health, allocator state, and rejection analysis
---

# Signals

Deep dive into the signal generation pipeline: feature health, signal quality, allocation decisions, and rejection analysis.

## Widgets & Cards

### Filters Bar
Filter by symbol, signal type, time range, and status.

### Status Strip
Pipeline status: signals generated/sec, approval rate, top rejection reasons.

### Why-Not-Trading
Diagnostic panel explaining why specific symbols aren't generating trades.

### Pipeline Funnel
Visual funnel: Raw Signals → Filtered → Risk-Checked → Allocated → Executed.

### Event Stream
Real-time feed of signal events with decision outcomes.

### Allocator State
Current allocation weights per symbol with target vs actual.

### Feature Health
Table of ML features with staleness, drift score, and importance ranking.

## Modals & Drawers

### Symbol Drawer
Detailed signal analysis for a single symbol: recent signals, feature values, rejection history.

## Actions

- Filter signals by any dimension
- Inspect individual signal decisions
- View feature importance rankings
- Export signal data

## Related Pages

- [Pipeline Health](/pipeline-health) — Engine layer monitoring
- [Market Context](/market-context) — Regime analysis
- [Live Trading](/live) — Real-time monitoring
