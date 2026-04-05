---
path: /analysis/replay
title: Replay Studio
group: Analysis
description: Decision forensics with event replay, anomaly detection, and compare mode
---

# Replay Studio

Forensic analysis tool for replaying trading decisions, detecting anomalies, and comparing outcomes.

## Widgets & Cards

### Replay Header
Selected time range, symbol, and replay controls (play, pause, step, speed).

### Event Filters
Filter replay events by type: decisions, orders, fills, guardrails, market data.

### Anomaly Lanes
Swim lanes highlighting anomalous events: unusual latency, unexpected rejections, price spikes.

### Context Panel
Side panel showing market state at the selected point in time.

### Compare Mode
Split view comparing two time periods or two symbols side-by-side.

### Regime Signals
Overlay of regime change signals on the replay timeline.

## Modals & Drawers

### Post-Mortem
Detailed analysis of a specific incident with timeline, root cause, and impact assessment.

## Actions

- Select time range for replay
- Step through events one by one
- Toggle anomaly detection
- Enter compare mode
- Export replay data
- Generate post-mortem report

## Related Pages

- [Signals](/signals) — Signal analysis
- [Pipeline Health](/pipeline-health) — Engine monitoring
- [Incidents](/risk/incidents) — Risk incidents
