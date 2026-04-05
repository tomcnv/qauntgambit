---
path: /backtesting
title: Backtesting
group: Research
description: Run, compare, and analyze strategy backtests with walk-forward validation
---

# Backtesting

Research workbench for running backtests, comparing strategies, and validating with walk-forward analysis.

## Widgets & Cards

### Live State Card
Current bot state summary for context when designing backtests.

### Runs Tab
Table of all backtest runs with status, date range, strategy, PnL, Sharpe, Max DD.

### New Backtest Tab
Form to configure and launch a new backtest: strategy, symbols, date range, capital, risk params.

### Compare Tab
Side-by-side comparison of two or more backtest runs with equity curves and metrics.

### Walk-Forward Tab
Walk-forward validation results showing in-sample vs out-of-sample performance.

### Datasets Tab
Available historical data with coverage, gaps, and quality scores.

## Modals & Drawers

### Run Detail Drawer
Full backtest results: equity curve, trade list, drawdown chart, monthly returns, risk metrics.

## Actions

- Launch a new backtest
- Compare multiple runs
- Clone a run with modified parameters
- Export results to CSV
- Delete old runs

## Related Pages

- [Data Quality](/data-quality) — Feed health
- [Signals](/signals) — Signal analysis
- [Trade History](/history) — Live trade comparison
