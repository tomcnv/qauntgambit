---
path: /data-quality
title: Data Quality
group: Research
description: Market data feed health monitoring with gap detection and quality scoring
---

# Data Quality

Monitor the health and completeness of market data feeds across all symbols and timeframes.

## Widgets & Cards

### Summary Strip
Total Symbols, Healthy %, Degraded %, Critical %, Overall Quality Score.

### Symbol Health Table
Per-symbol quality metrics: quality score, gap count, staleness, last update, status badge.

### Alerts
Active data quality alerts with severity and affected symbols.

### Gap Timeline
Visual timeline showing data gaps per symbol over the selected period.

### Quality Trend
Line chart of aggregate quality score over time.

## Modals & Drawers

### Symbol Detail Drawer
Deep dive into a single symbol: candle coverage, gap locations, latency distribution, outlier detection.

### Backfill Dialog
Trigger a data backfill for a symbol/timeframe range with progress tracking.

## Actions

- Filter symbols by quality status
- Trigger backfill for gaps
- Export quality report
- Configure quality thresholds

## Related Pages

- [Backtesting](/backtesting) — Strategy research
- [Pipeline Health](/pipeline-health) — Engine monitoring
- [Signals](/signals) — Signal health
