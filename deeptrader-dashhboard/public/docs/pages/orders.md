---
path: /orders
title: Orders & Fills
group: Trading
description: Order tracking with fill rates, latency distribution, and execution quality metrics
---

# Orders & Fills

Comprehensive order management view showing all orders across the fleet with execution quality analytics.

## Widgets & Cards

### KPI Cards
Total Orders, Fill Rate %, Avg Fill Latency, Rejection Rate, Slippage (bps).

### Latency Distribution
Histogram of order-to-fill latency with P50/P95/P99 markers.

### Fill Rate Breakdown
Stacked bar chart showing fill/partial/reject/cancel rates by exchange and symbol.

### Orders Table
Sortable, filterable table of all orders with columns: Time, Symbol, Side, Size, Price, Status, Latency, Slippage.

## Modals & Drawers

### Pending Order Sheet
Detail view of a pending order with cancel/replace actions.

### Trade Inspector
Full trade lifecycle view from signal through fill.

## Actions

- Filter orders by status, symbol, exchange, time range
- Cancel a pending order
- Replace a pending order
- Export orders to CSV
- Inspect trade lifecycle

## Settings & Knobs

- Default time range filter
- Auto-refresh interval
- Columns visible in orders table

## Related Pages

- [Live Trading](/live) — Real-time monitoring
- [Trade History](/history) — Completed trades
- [Execution](/execution) — TCA analysis
