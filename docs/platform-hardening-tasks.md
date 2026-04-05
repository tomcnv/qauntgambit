# Platform Hardening Task Tracker

## Status legend

- `[ ]` pending
- `[-]` in progress
- `[x]` completed

## Current focus

### Phase 1. Baseline stabilization

- [x] Define hardening roadmap and workstreams.
- [x] Add startup schema preflight for local stack.
- [x] Wire startup to fail closed before PM2 when required tables are missing.
- [x] Reduce Docker bootstrap to infra-only setup.
- [x] Add conservative local golden schema apply step for uninitialized DBs.
- [-] Add explicit platform schema apply/check flow.
- [-] Add explicit quant schema apply/check flow.

### Phase 2. Identity and auth correctness

- [-] Remove unauthenticated mutation defaults.
- [-] Remove synthetic tenant/user/bot fallbacks from bot APIs.
- [-] Standardize canonical identity contract across services and queue scope.

### Phase 3. Runtime determinism

- [-] Make control-manager exported env the only supported runtime launch contract.
- [-] Remove duplicate runtime env override layers.
- [-] Centralize symbol mapping per exchange and storage key.
- [x] Enforce model feature compatibility from deployed model config at runtime startup.

### Phase 4. Observability and drift controls

- [-] Add bot launch preflight diagnostics.
- [x] Add schema drift diagnostics.
- [-] Add runtime env drift diagnostics.
- [x] Add model contract drift diagnostics.

### Phase 5. Trading performance iteration

- [ ] Instrument rejection reasons by gate and symbol.
- [ ] Simplify gate stack and threshold surface area.
- [ ] Add live/demo rollout safety checks.

## Completed in this pass

- [x] Docker bootstrap now provisions infra only, not app tables.
- [x] Local startup applies golden schemas conservatively for uninitialized DBs.
- [x] Local startup fails closed on missing required platform/quant tables.
- [x] Disabled auth no longer fabricates tenant/user claims unless `AUTH_ALLOW_DEV_IDENTITY_FALLBACK=true`.
- [x] Runtime launch now passes `ENV_FILE` explicitly to PM2-managed bot processes.
- [x] Bot control and runtime-config endpoints now require explicit `tenant_id` and `bot_id`.
- [x] Added `/api/dashboard/runtime-config/preflight` for launch-blocker visibility.
- [x] Control-manager now defaults to strict config parity and blocks launch on missing payload mappings.
- [x] Added local golden-schema drift diagnostics for platform and quant databases.
- [x] Added `/api/dashboard/runtime-config/drift` to compare expected vs last-launched runtime env.
- [x] Tightened dashboard execution-control endpoints to require explicit scope.
- [x] Added ownership checks to bot-instance exchange mutation endpoints.
- [x] `_requested_user_id` now rejects tenant overrides that do not match the authenticated scope.
- [x] Added canonical `to_ccxt_market_symbol(...)` helper and wired dashboard manual close to use it.
- [x] Runtime market-data symbol conversion now uses the shared CCXT symbol helper.
- [x] Destructive dashboard history-clearing endpoints now require explicit scope.
- [x] `ccxt_clients` now uses the shared CCXT symbol helper instead of its own ad hoc conversion path.
- [x] Added `/api/monitoring/model-contract` for model config vs env contract drift visibility.
- [x] Bot-profile write paths now bind create/activate/set-active to the authenticated owner.
- [x] Additional bot-instance lifecycle, budget, rollback, and symbol-management writes now enforce ownership.
- [x] Local startup now hard-fails on schema drift instead of warning and continuing.
- [x] Local schema bootstrap now records the golden baseline checksum per database.
- [x] Quant migration runner defaults now target `quantgambit_bot` / `quantgambit`.
- [x] Control queue service now requires explicit `tenant_id` and `bot_id` for command streams and locks.
- [x] Redis stream naming helpers now reject unscoped command/control stream usage.
- [x] JWT claim extraction now keeps `user_id` and `tenant_id` explicit, with `AUTH_USER_ID_AS_TENANT` as the bridge knob.
- [x] Symbol canonicalization now has a shared storage-symbol helper used by reconciliation and runtime paths.
- [x] Quant open-order fetching now derives CCXT symbol attempts from the shared symbol contract.
- [x] Node control symbol normalization now mirrors the current Python exchange rules more closely.
- [x] Bot exchange config creation now rejects ambiguous legacy+new account linkage in the same payload.
- [x] `require_explicit=True` scope resolution now truly ignores default tenant/bot env fallbacks.
- [x] Control command publishing now hard-fails when request scope is missing.
- [x] Owner-scoped user resolution no longer falls back to `DEFAULT_USER_ID` unless explicitly enabled.
- [x] Replay session creation and slippage autotune now require explicit tenant/bot scope.
- [x] API symbol alias/candidate helpers now use shared storage-symbol normalization in key read/query paths.
- [x] Backtest preflight symbol candidate normalization now uses the shared storage-symbol helper.
- [x] Runtime orderbook symbol normalization now uses the shared canonical symbol helper for bybit/binance.
- [x] Legacy `deeptrader-backend/scripts/run-migrations.js` now delegates to `run_all_migrations.sh` instead of acting as a competing migration entrypoint.
- [x] `start-dev.sh` now reconciles platform migrations through `deeptrader-backend/run_all_migrations.sh`.
- [x] Added ECS quant migration override entrypoint at `scripts/aws/ecs-overrides/apply_all_quant_migrations.json`.
- [x] `ecosystem.config.js` now resolves one authoritative quant Python interpreter instead of mixing `venv` and `venv311`.
- [x] `start-dev.sh` no longer supports the legacy nohup startup branch; local startup goes through the hardened PM2 path only.
- [x] PM2 defaults no longer inject ambient `DEFAULT_TENANT_ID` / `DEFAULT_BOT_ID` into `quantgambit-api`.
- [x] Runtime launch now requires explicit runtime context (`TENANT_ID`, `BOT_ID`, `ACTIVE_EXCHANGE`, `TRADING_MODE`) and an explicit credential reference.
- [x] Runtime launch no longer falls back from bot DB settings to platform DB defaults.
- [x] `.env`-driven runtime tuning overrides are now gated behind `RUNTIME_DEV_OVERRIDES=true` instead of applying implicitly.
- [x] Local secret autodetect in `launch-runtime.sh` is now behind `ALLOW_LOCAL_SECRET_AUTODETECT=true`.
- [x] `launch-spot-bot.sh` now forwards into the canonical runtime launcher instead of starting PM2 runtimes directly.
- [x] `launch-runtime.sh` now requires explicit execution/routing context (`MARKET_TYPE`, `EXECUTION_PROVIDER`, `ORDERBOOK_SOURCE`, `TRADE_SOURCE`, `MARKET_DATA_PROVIDER`, `ORDERBOOK_SYMBOLS`) instead of silently defaulting them.
- [x] ONNX runtime launch now hard-fails when required model contract fields are missing.
- [x] Runtime launch now emits and injects a deterministic `LAUNCH_RUNTIME_CONTRACT_HASH` / version for auditability and optional integrity enforcement.

## Notes

- Current local required platform tables:
  - `users`
  - `exchange_accounts`
  - `bot_instances`
  - `user_trading_settings`
  - `bot_exchange_configs`
- Current local required quant tables:
  - `bot_configs`
  - `orderbook_snapshots`
  - `trade_records`
  - `order_states`
  - `order_events`
  - `decision_events`
  - `recorded_decisions`
  - `schema_migrations`
