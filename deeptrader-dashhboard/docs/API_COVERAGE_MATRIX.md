# Dashboard API Coverage Matrix

## Overview
This document maps each frontend page to its data dependencies and backend endpoints.

## Route → Page → Data → Endpoint Matrix

**Status meanings**

- ✅ **Connected**: Uses real backend APIs for the page’s primary UI (no mock/placeholder powering the UI).
- ⚠️ **Partial**: Some widgets are real, but parts still use mock/generated placeholders or hardcoded values.
- ❌ **Mock**: Page is primarily driven by mock/generated placeholder data.
- 🧩 **Missing BE**: Frontend expects functionality that doesn’t exist yet in the backend.

### Trading Section
| Route | Page | Mock Data | Backend Endpoint | Status |
|-------|------|-----------|------------------|--------|
| `/dashboard` | `overview.tsx` | - | `useOverviewData` → `/api/monitoring/*`, `/api/bot/status`, `/api/dashboard/*` (as available) | ⚠️ Partial |
| `/dashboard/live` | `live-trading.tsx` | **Still** uses `mockStrategies`, `mockCancels`, `mockRejects`, `mockTimeline` (and hardcoded bot metadata) | `useTradingOpsData` → `/api/dashboard/trading`; `useIntelligenceData`; `useMarketContext` | ⚠️ Partial |
| `/dashboard/orders` | `orders.tsx` | now uses `/dashboard/pending-orders` & `/dashboard/execution` (no mock) | `/api/dashboard/pending-orders`, `/api/dashboard/execution` | ⚠️ Partial (depends on exec stats shape) |
| `/dashboard/positions` | `positions-risk.tsx` | Has mock fallback via `mockPositions`; some actions are placeholders | `useExchangePositions` → `/api/dashboard/exchange-positions` (plus missing close/flatten actions) | ⚠️ Partial |
| `/dashboard/history` | `history.tsx` | now uses `/dashboard/trade-history` (no mock) | `/api/dashboard/trade-history` | ⚠️ Partial (UI depends on stats shape) |
| `/dashboard/active-bot` | `active-bot.tsx` | (verify) likely contains placeholders/hardcoded metadata | Should use `/api/bot-instances/active` + `/api/dashboard/*` snapshots | ⚠️ Partial |

### Risk Section
| Route | Page | Mock Data | Backend Endpoint | Status |
|-------|------|-----------|------------------|--------|
| `/dashboard/risk/limits` | `risk-limits.tsx` | - | `/api/bot-instances/policy` (+ related settings endpoints) | ⚠️ Partial |
| `/dashboard/risk/exposure` | `risk-exposure.tsx` | `exposureBySymbol`, `exposureHistory`, `leverageHistory`, `marginData` (placeholders) | **Needs wiring** to `/api/dashboard/risk` + `/api/dashboard/positions` | ❌ Mock |
| `/dashboard/risk/metrics` | `risk-metrics.tsx` | `mockVarDistribution`, `mockVarHistory`, `mockScenarios`, etc. | 🧩 Missing/unclear: `/api/risk/*` endpoints need verification/implementation | 🧩 Missing BE |
| `/dashboard/risk/incidents` | `risk-incidents.tsx` | now uses `useIncidents` (fallback none) | `/api/replay/incidents` | ⚠️ Partial |
| `/dashboard/risk/replay` | `replay-studio.tsx` | heavy mock generator (`generateMockEvents`, mock candles/pnl/trace/features) | `/api/replay/*` (authenticated) + traces/decisions endpoints | ❌ Mock |

### Analysis Section  
| Route | Page | Mock Data | Backend Endpoint | Status |
|-------|------|-----------|------------------|--------|
| `/dashboard/market-context` | `market-context.tsx` | still has `mockSymbols` fallback | `useMarketContext` → `/api/dashboard/market-context` | ⚠️ Partial |
| `/dashboard/signals` | `signals.tsx` | still includes mock pipeline/events/allocator/trace constants as fallback | `useSignalLabData`, `useHealthSnapshot`, `/api/dashboard/signals` | ⚠️ Partial |
| `/dashboard/execution` | `execution.tsx` | `slippageBySymbol`, `hourlyExecution`, `orderTypes` (placeholders) | `/api/tca/*` | ❌ Mock |
| `/dashboard/tca` | `tca.tsx` | (verify) may contain placeholders | `/api/tca/analysis`, `/api/tca/capacity`, `/api/tca/cost` | ⚠️ Partial |

### Research Section
| Route | Page | Mock Data | Backend Endpoint | Status |
|-------|------|-----------|------------------|--------|
| `/dashboard/backtesting` | `backtesting.tsx` | still includes mock curve/trades/WFO results and uses mock fallbacks | `/api/research/backtests`, `/api/research/backtests/:id`, `/api/research/datasets` | ⚠️ Partial |
| `/dashboard/replay` | `replay.tsx` | (verify) check for placeholder session lists | `/api/replay/sessions`, `/api/replay/incidents` | ⚠️ Partial |
| `/dashboard/data-quality` | `data-quality.tsx` | mock fallbacks for health/alerts/gaps/history | `/api/data-quality/*` (authenticated) | ⚠️ Partial |

### System Section
| Route | Page | Mock Data | Backend Endpoint | Status |
|-------|------|-----------|------------------|--------|
| `/dashboard/bot-management` | `bot-management.tsx` | - | `/api/bot-instances/*`, `/api/exchange-credentials/*` | ✅ Connected |
| `/dashboard/profiles` | `profiles.tsx` | (verify) likely has placeholders for some list/detail widgets | `/api/bot-config/profile-specs`, `/api/bot-config/profiles/*` | ⚠️ Partial |
| `/dashboard/strategies` | `strategies.tsx` | mock fallback still present | `/api/bot-config/strategies` (templates) + strategy instances endpoints (if supported) | ⚠️ Partial |
| `/dashboard/audit` | `audit.tsx` | - | `/api/audit` | ✅ Connected |

### Settings Section
| Route | Page | Mock Data | Backend Endpoint | Status |
|-------|------|-----------|------------------|--------|
| `/dashboard/settings` | `settings/index.tsx` | some hardcoded tile statuses | `/api/bot-instances/policy` (+ `/api/auth/me` when added) | ⚠️ Partial |
| `/dashboard/settings/account` | `settings/account.tsx` | verify (likely placeholders) | `/api/settings/account` (new) | ⚠️ Partial |
| `/dashboard/settings/trading` | `settings/trading.tsx` | verify (may contain placeholders) | `/api/settings/trading` | ⚠️ Partial |
| `/dashboard/settings/risk` | `settings/risk.tsx` | - | `/api/bot-instances/policy` | ✅ Connected |
| `/dashboard/settings/exchanges` | `settings/exchanges.tsx` | - | `/api/exchange-credentials/*` | ✅ Connected |
| `/dashboard/settings/notifications` | `settings/notifications.tsx` | likely placeholders | `/api/settings/notifications/*` (new) | ⚠️ Partial |
| `/dashboard/settings/data` | `settings/data.tsx` | likely placeholders | 🧩 needs `/api/settings/data` | 🧩 Missing BE |
| `/dashboard/settings/security` | `settings/security.tsx` | likely placeholders (2FA etc.) | `/api/auth/*` | ⚠️ Partial |
| `/dashboard/settings/billing` | `settings/billing.tsx` | placeholders | External (Stripe) | ❌ Mock |

## Backend Endpoints Available

### Dashboard Routes (`/api/dashboard/*`)
- `GET /state` - Full state snapshot
- `GET /positions` - Current positions
- `GET /pending-orders` - Open orders
- `GET /metrics` - Bot metrics
- `GET /risk` - Risk metrics
- `GET /trading` - Combined trading snapshot
- `GET /signals` - Signal snapshot
- `GET /market-context` - Market context data
- `GET /candles/:symbol` - Candlestick data
- `GET /drawdown` - Drawdown data
- `GET /trade-history` - Trade history
- `GET /exchange-positions` - Direct exchange positions
- `GET /orphaned-positions` - Orphaned positions

### Data Quality Routes (`/api/data-quality/*`)
- `GET /metrics` - Quality metrics
- `GET /gaps` - Feed gaps
- `GET /alerts` - Quality alerts
- `GET /health` - Symbol health

### Research Routes (`/api/research/*`)
- `GET /backtests` - List backtests
- `POST /backtests` - Create backtest
- `GET /backtests/:id` - Backtest detail
- `GET /datasets` - Available datasets
- `GET /walk-forward` / `GET /walk-forward/:id` / `POST /walk-forward` - Walk-forward optimization (temporary Redis-backed)

### Bot Instances Routes (`/api/bot-instances/*`)
- Full CRUD for bot instances, exchange configs, symbol configs
- Tenant risk policy management
- Active config queries

### Strategy Instances Routes (`/api/strategy-instances/*`)
- Redis-backed CRUD for strategy instances (temporary)

### Settings Routes (`/api/settings/*`)
- `GET/PUT /account` - Tenant/account preferences (Redis-backed)
- `GET/POST/PUT/DELETE /notifications/channels` - Notification channels
- `GET/PUT /notifications/routing` - Notification routing rules
- `POST /notifications/test` - Test notification dispatch

## Priority Action Items

### Remaining wiring work (high signal)
1. Remove **all** mock/placeholder arrays from: `orders.tsx`, `history.tsx`, `risk-exposure.tsx`, `risk-incidents.tsx`, `risk-metrics.tsx`, `execution.tsx`, `replay-studio.tsx`.
2. Remove mock fallbacks from partially wired pages: `live-trading.tsx`, `positions-risk.tsx`, `signals.tsx`, `market-context.tsx`, `data-quality.tsx`, `backtesting.tsx`, `strategies.tsx`.
3. Backend now provides account + notifications + strategy-instances + walk-forward (Redis-backed); still need risk analytics endpoints and replay studio data shape for full fidelity.

