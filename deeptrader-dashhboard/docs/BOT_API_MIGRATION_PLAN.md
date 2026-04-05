# Bot API Migration Plan (Dashboard → QuantGambit)

Goal: make the dashboard fully functional against the QuantGambit bot API while keeping auth/settings in deeptrader‑backend.

## Ownership rules (applied)
- **Core (dashboard‑backend)**: `/auth/*`, `/settings/*`, `/exchange-credentials/*`, `/exchange-accounts/*`, `/user-profiles/*`, `/deployment/*`, `/symbol-locks/*`, `/promotions/*`, `/audit/*`, `/config-validation/*`, `/models/*`.
- **Bot (QuantGambit)**: everything else (`/bot/*`, `/dashboard/*`, `/monitoring/*`, `/runtime/*`, `/history/*`, `/risk/*`, `/tca/*`, `/replay/*`, `/data-quality/*`, `/research/*`, `/reporting/*`).

## Phase 0 — Confirm plumbing (done)
- Dashboard uses `VITE_CORE_API_BASE_URL` → core backend (3001)
- Dashboard uses `VITE_BOT_API_BASE_URL` → QuantGambit (3002)
- Raw `fetch('/api/...')` calls converted to `apiFetch` so routing works

## Phase 1 — Minimum viable dashboard (highest impact)
Focus: overview + live trading + orders/positions + bot control.

**Endpoints to implement or map in QuantGambit:**
- `/bot/control`, `/bot/start`, `/bot/stop`, `/bot/emergency-stop`
- `/dashboard/positions`, `/dashboard/pending-orders`, `/dashboard/trade-history`
- `/dashboard/cancel-all-orders`, `/dashboard/close-all-positions`, `/dashboard/orders/cancel`, `/dashboard/orders/replace`, `/dashboard/close-position`
- `/monitoring/fast-scalper/rejections`, `/monitoring/fast-scalper/logs`
- `/monitoring/runtime-config`
- `/dashboard/live-status`, `/dashboard/state`, `/dashboard/warmup`

**Implementation strategy:**
- Backed by existing QuantGambit snapshots:
  - `runtime/orders`, `runtime/positions`, `runtime/risk`, `runtime/quality`
  - `history/orders`, `history/decisions`, `history/guardrails`, `history/predictions`
- Create thin “compat” endpoints in QuantGambit that shape‑convert payloads for the current dashboard fields.

## Phase 2 — Monitoring + Health + Risk
Focus: system health, guardrails, and risk panels.

**Endpoints:**
- `/dashboard/risk/limits`, `/risk/limits`
- `/risk/exposure`, `/risk/metrics`, `/risk/var`, `/risk/scenarios`, `/risk/correlations`, `/risk/component-var`
- `/risk/incidents`, `/risk/incidents/snapshot`, `/dashboard/risk/incidents`
- `/monitoring/dashboard`, `/monitoring/alerts`
- `/data-quality/health`, `/data-quality/metrics`, `/data-quality/metrics/timeseries`, `/data-quality/gaps`, `/data-quality/alerts`

**Implementation strategy:**
- Map to QuantGambit telemetry + Timescale tables.
- Expose aggregated risk/health summaries for UI without changing UI shape initially.

## Phase 3 — Replay + Research + Reporting
Focus: replay tools, backtesting, and reporting panels.

**Endpoints:**
- `/replay/sessions`, `/replay/summary`, `/replay/compare`, `/replay/annotations`, `/replay/features/dictionary`
- `/research/backtests`, `/research/datasets`, `/research/walk-forward`
- `/reporting/templates`, `/reporting/reports`, `/reporting/portfolio/summary`, `/reporting/portfolio/strategies`, `/reporting/portfolio/correlations`

**Implementation strategy:**
- Backed by Timescale + bot DB tables already used by exports.
- Keep payloads aligned with current dashboard expectations; add a thin transform layer.

## Phase 4 — Bot configuration UI
Focus: config editor + profile router + strategies UI.

**Endpoints:**
- `/bot-config/*` (profiles, strategies, profile router, active bot, versions)
- `/bot-instances/*` (instances, active bot, policy, templates, enable live)
- `/dashboard/profiles`, `/dashboard/strategies`, `/dashboard/strategy-status`, `/dashboard/profile-editor`

**Implementation strategy:**
- Decide whether QuantGambit should host these routes or they stay in core.
- If moved to bot, use QuantGambit config store and versioning.

## Phase 5 — Cleanup
- Remove mock fallbacks in UI once APIs are verified.
- Add contract tests to prevent endpoint drift.

## Immediate next action
Pick the **Phase 1** endpoints to implement first; I’ll start wiring the compat endpoints in QuantGambit and update the dashboard hooks where needed.
