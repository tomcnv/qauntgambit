# Dashboard → Bot API Coverage

This is an automated snapshot of dashboard-used API paths and whether they exist in QuantGambit API.

## Bot paths referenced by dashboard (normalized)

- `/bot-config/active-bot` — **bot**
- `/bot-config/bots` — **bot**
- `/bot-config/profile-metrics` — **bot**
- `/bot-config/profile-router` — **bot**
- `/bot-config/profile-specs` — **bot**
- `/bot-config/strategies` — **bot**
- `/bot-instances` — **bot**
- `/bot-instances/active` — **bot**
- `/bot-instances/policy` — **bot**
- `/bot-instances/policy/enable-live` — **bot**
- `/bot-instances/templates` — **bot**
- `/bot-management` — **bot**
- `/bot/control` — **bot**
- `/bot/emergency-stop` — **bot**
- `/bot/start` — **bot**
- `/bot/stop` — **bot**
- `/bots/` — **bot**
- `/dashboard/*` — **bot**
- `/dashboard/bots` — **bot**
- `/dashboard/cancel-all-orders` — **bot**
- `/dashboard/close-all-orphaned` — **bot**
- `/dashboard/close-all-positions` — **bot**
- `/dashboard/close-position` — **bot**
- `/dashboard/exchange-positions` — **bot**
- `/dashboard/execution` — **bot**
- `/dashboard/history` — **bot**
- `/dashboard/market-context` — **bot**
- `/dashboard/orders/cancel` — **bot**
- `/dashboard/orders/replace` — **bot**
- `/dashboard/orphaned-positions` — **bot**
- `/dashboard/pending-orders` — **bot**
- `/dashboard/positions` — **bot**
- `/dashboard/profile-editor` — **bot**
- `/dashboard/profiles` — **bot**
- `/dashboard/risk/incidents` — **bot**
- `/dashboard/risk/limits` — **bot**
- `/dashboard/signals` — **bot**
- `/dashboard/sl-tp-events` — **bot**
- `/dashboard/state` — **bot**
- `/dashboard/strategies` — **bot**
- `/dashboard/strategy-status` — **bot**
- `/dashboard/trade-history` — **bot**
- `/dashboard/trading` — **bot**
- `/dashboard/warmup` — **bot**
- `/data-quality/alerts` — **bot**
- `/data-quality/gaps` — **bot**
- `/data-quality/health` — **bot**
- `/data-quality/metrics` — **bot**
- `/data-quality/metrics/timeseries` — **bot**
- `/monitoring/alerts` — **bot**
- `/monitoring/dashboard` — **bot**
- `/monitoring/fast-scalper/logs` — **bot**
- `/monitoring/fast-scalper/rejections` — **bot**
- `/monitoring/runtime-config` — **bot**
- `/python/bot/status` — **bot**
- `/replay/annotations` — **bot**
- `/replay/compare` — **bot**
- `/replay/features/dictionary` — **bot**
- `/replay/sessions` — **bot**
- `/replay/summary` — **bot**
- `/reporting/portfolio/correlations` — **bot**
- `/reporting/portfolio/strategies` — **bot**
- `/reporting/portfolio/summary` — **bot**
- `/reporting/reports` — **bot**
- `/reporting/templates` — **bot**
- `/research/backtests` — **bot**
- `/research/datasets` — **bot**
- `/research/walk-forward` — **bot**
- `/risk/component-var` — **bot**
- `/risk/correlations` — **bot**
- `/risk/exposure` — **bot**
- `/risk/incidents` — **bot**
- `/risk/incidents/snapshot` — **bot**
- `/risk/limits` — **bot**
- `/risk/metrics` — **bot**
- `/risk/scenarios` — **bot**
- `/risk/scenarios/factors` — **bot**
- `/risk/var` — **bot**
- `/risk/var/force-snapshot` — **bot**
- `/risk/var/historical` — **bot**
- `/risk/var/monte-carlo` — **bot**
- `/risk/var/snapshot` — **bot**
- `/risk/var/trigger-refresh` — **bot**
- `/tca/analysis` — **bot**

## QuantGambit API routes (Phase 1 + compat)

- `/backtests`
- `/backtests/{backtest_id}`
- `/history/decisions`
- `/history/guardrails`
- `/history/orders`
- `/history/predictions`
- `/runtime/config`
- `/runtime/guardrails`
- `/runtime/health`
- `/runtime/orders`
- `/runtime/overrides`
- `/runtime/positions`
- `/runtime/quality`
- `/runtime/risk`
- `/bot-config/*`
- `/bot-instances/*`
- `/bot-management`
- `/bot/*`
- `/bots`
- `/dashboard/*`
- `/data-quality/*`
- `/monitoring/*`
- `/python/bot/status`
- `/replay/*`
- `/reporting/*`
- `/research/*`
- `/risk/*`
- `/tca/*`

## Missing in QuantGambit (dashboard uses, bot API lacks)

- None (Phase 1 compatibility stubs added in QuantGambit API).

## Covered by QuantGambit

- All dashboard-referenced bot endpoints listed above are now present as compat stubs or fully-backed routes.

## Core routes referenced by dashboard (should remain in deeptrader-backend)
