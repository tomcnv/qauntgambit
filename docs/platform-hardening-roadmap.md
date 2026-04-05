# QuantGambit Platform Hardening Roadmap

## Objective

Make the platform deterministic, auditable, and safe enough to iterate on live trading logic without hidden schema drift, identity drift, or runtime config drift.

## Guiding principles

- One schema authority per database.
- One runtime config authority per launched bot.
- Fail closed on missing schema, invalid identity, or incompatible model/runtime contracts.
- Remove silent defaults from mutation and trading paths.
- Make every launch reproducible from stored metadata.

## Workstreams

### 1. Schema governance

Goals:
- Platform DB has one source of truth.
- Quant DB has one source of truth.
- Docker bootstrap only provisions infrastructure, not app tables.

Deliverables:
- Platform golden schema ownership documented and enforced.
- Quant golden schema ownership documented and enforced.
- Startup schema preflight.
- Migration runner strategy for both DBs.
- Archive and retire conflicting bootstrap SQL.

### 2. Identity and auth hardening

Goals:
- No synthetic tenant/user/bot identities in runtime-critical flows.
- No unauthenticated state mutation paths.

Deliverables:
- Remove default tenant/user fallbacks from bot and runtime APIs.
- Remove unauthenticated mutation behavior from local stack.
- Enforce explicit `user_id`, `tenant_id`, `bot_id`, and `exchange_account_id` resolution.

### 3. Runtime contract simplification

Goals:
- Runtime launch is deterministic.
- Model contract is derived from deployed model metadata, not stale env.
- Symbol handling is canonical across market data and execution.

Deliverables:
- Control-manager exported runtime env becomes authoritative.
- Runtime launcher consumes one env contract.
- Centralized symbol adapter contract per exchange.
- Stored launch metadata: config version, model version, env hash.

### 4. Operational readiness and diagnostics

Goals:
- Platform readiness reflects real end-to-end operability.
- Launch failures are explicit before the bot starts.

Deliverables:
- Startup preflight checks.
- Bot launch preflight checks.
- Drift diagnostics for schema, runtime env, and model contract.
- Unified readiness endpoint/dashboard.

### 5. Trading system competitiveness

Goals:
- Reduce noise from config entropy.
- Make rejections explainable and tunable.

Deliverables:
- Simplified gate hierarchy.
- Structured rejection telemetry with one primary reason.
- Model rollout discipline and compatibility enforcement.
- Shadow/paper/live execution modes on the same validated runtime path.

## Execution order

### Phase 1. Stabilize baseline

1. Add schema preflight to startup.
2. Stop Docker bootstrap from owning app schema.
3. Document and enforce golden schema ownership.
4. Fail startup when required platform or quant tables are missing.

### Phase 2. Fix identity and auth correctness

1. Remove default tenant and bot fallbacks from runtime-critical APIs.
2. Disable unauthenticated mutation behavior.
3. Normalize identity semantics across platform and quant services.

### Phase 3. Fix runtime determinism

1. Collapse runtime env generation to one authority.
2. Remove duplicate env override behavior.
3. Canonicalize symbol formatting through exchange adapters.
4. Enforce model feature contract compatibility at launch time.

### Phase 4. Add readiness and drift visibility

1. Add startup and launch preflight APIs.
2. Add schema drift diagnostics.
3. Add runtime env parity diagnostics.
4. Add model/runtime compatibility diagnostics.

### Phase 5. Tune the trading engine

1. Measure rejection reasons and no-signal rates by gate and symbol.
2. Simplify gates and thresholds.
3. Tighten live/demo rollout discipline.
4. Iterate on strategy/model logic once platform integrity is trustworthy.

## Success criteria

- Fresh startup produces a runnable stack or fails before PM2 starts.
- Missing schema cannot hide behind green health checks.
- Bot launch cannot proceed with synthetic identities or incomplete config.
- Runtime env, model contract, and schema versions are inspectable and reproducible.
- Trading decisions and rejections are attributable to explicit structured causes.
