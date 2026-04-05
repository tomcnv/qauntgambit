---
path: /pipeline-health
title: Pipeline Health
group: Analysis
description: Engine layer monitoring with status, latency, throughput, and worker health
---

# Pipeline Health

Monitor the health of every layer in the trading pipeline: data ingestion, signal generation, decision making, and execution.

## Widgets & Cards

### Layer Cards
One card per pipeline layer showing: status (healthy/degraded/critical), latency (P50/P95), throughput (events/sec), error rate.

### Status Timeline
Gantt-style timeline showing layer health over the last hour.

### Latency Breakdown
Stacked bar chart showing per-layer latency contribution to total decision latency.

### Throughput Chart
Line chart of events processed per second across all layers.

### Worker Health
Table of active workers with CPU, memory, queue depth, and last heartbeat.

## Actions

- Drill down into any layer for detailed metrics
- View error logs for degraded layers
- Restart a stalled worker
- Export health report

## Related Pages

- [Live Trading](/live) — Real-time bot monitoring
- [Signals](/signals) — Signal pipeline details
- [Execution](/execution) — Execution quality
