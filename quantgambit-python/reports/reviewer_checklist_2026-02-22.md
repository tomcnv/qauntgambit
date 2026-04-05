# QuantGambit External Review Checklist (2026-02-22)

## Review Goal
Determine if the current live system is safe to keep in production and what must be fixed before scaling risk.

## Current Runtime Baseline (Must Match)
- `TRADING_MODE=live`
- `TRADING_DISABLED=false`
- `SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT`
- `PREDICTION_PROVIDER=onnx`
- `PREDICTION_REQUIRE_PRESENT=true`
- `PREDICTION_SCORE_GATE_ENABLED=true`
- `PREDICTION_SCORE_GATE_MODE=fallback_heuristic`
- `EV_GATE_MODE=enforce`
- `MIN_NET_EDGE_BPS=35.0`
- `ENABLE_UNIFIED_CONFIRMATION_POLICY=true`
- `CONFIRMATION_POLICY_MODE=enforce`
- `ENTRY_EXECUTION_MODE=auto`
- `POSITION_GUARD_ENABLED=true`

## Immediate Red-Flag Checks (Fail-Fast)
1. Runtime heartbeat
- Bot status API reports `running`, decision and execution workers healthy.
2. Data feed integrity
- No persistent websocket disconnect; orderbook/trade/candle freshness inside configured limits.
3. Prediction availability
- No prolonged `prediction_missing`/`prediction_blocked` across active symbols.
4. Trade history integrity
- New fills and closes appear in API/UI and match DB rows for the same time window.
5. Exit reason quality
- Close events include specific reason taxonomy (not generic `Position Closed` only).

## Directional Quality Gate
1. Side-level diagnostics
- Compute rolling directional accuracy for long and short separately.
- Confirm gate thresholds are respected:
- `PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY_LONG=0.40`
- `PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY_SHORT=0.65`
2. Calibration diagnostics
- Verify ECE bounds:
- `PREDICTION_SCORE_MAX_ECE_LONG=0.20`
- `PREDICTION_SCORE_MAX_ECE_SHORT=0.18`
3. Confidence sanity
- Check that high confidence predictions are not concentrated in losing outcomes.

Decision:
- If short directional quality fails, keep shorts disabled or side-suppressed until recovered.

## Cost/Execution Gate
1. Expected vs realized costs
- Compare expected total cost bps to realized cost bps per trade cohort.
2. Maker/taker attribution
- Verify each fill stores maker/taker flag and this is exposed in history.
3. Net edge enforcement
- Confirm rejected entries include cost-aware reason when net edge after buffer fails:
- `MIN_NET_EDGE_BPS=35.0`, `EV_GATE_COST_MULTIPLE=2.25`
4. Churn detection
- Flag repeated quick invalidation exits after entry as pre-entry filtering gap.

Decision:
- If realized costs dominate expected edge, tighten entry gates or execution policy before more risk.

## Unified Confirmation (Double Confirmation) Gate
1. Contract checks
- For every entry and non-emergency exit, verify trace fields:
- `confirmation_mode`, `confirmation_confidence`, `confirmation_votes`, `confirmation_reason_codes`
2. Behavior checks
- Emergency/critical exits must bypass confirmation.
- Non-emergency exits should apply configured vote/confidence thresholds.
3. Strategy overrides
- Validate overrides are bounded and loaded from `CONFIRMATION_POLICY_STRATEGY_OVERRIDES_JSON`.

Decision:
- No promotion if trace fields are missing or emergency bypass is blocked.

## Exit Control Gate
1. Exit distribution
- Measure share of exits by category: safety, invalidation, time budget, profit.
2. Hold-time coherence
- Compare hold durations to strategy horizon and `EXIT_SIGNAL_MIN_HOLD_SEC`.
3. Guardian behavior
- Confirm guardian is reducing catastrophic loss without causing systematic churn.

Decision:
- If invalidation exits dominate shortly after entry, pre-entry veto logic is insufficient.

## API and Observability Reliability Gate
1. Key pages/endpoints
- `/signals`, trade history, orders/fills, replay endpoints must return consistently.
2. 12h window stability
- No 500s/timeouts on heavy audit endpoints.
3. DB query health
- Critical audit queries use indexes and meet acceptable latency.

Decision:
- No promotion with broken audit visibility.

## Promotion Readiness Criteria (All Must Pass)
1. Positive rolling net expectancy after costs by symbol/side in target window.
2. Directional accuracy and ECE within configured bounds.
3. Forced/guardian exits below agreed cap.
4. No telemetry contract violations (missing reason/trace fields).
5. API reliability stable for operational windows.
6. No unresolved maker/taker or fill-cost attribution gaps.

## Test Execution Pack
1. Unit
- Prediction blocked reason propagation.
- Confirmation policy pass/fail paths.
- EV/cost math and min-edge veto.
- Exit reason mapping and urgency bypass.
2. Integration
- End-to-end decision trace parity across entry/exit.
- Prediction gate + fallback behavior by symbol.
- Trade history field completeness.
3. Replay
- Baseline vs updated logic over same window, with net markout comparison.
4. Operational
- p95 latency checks for heavy dashboard endpoints.
- Runtime health and stream lag checks.

## Handoff Artifacts for Reviewer
1. Parameter inventory
- `quantgambit-python/reports/parameter_audit_handoff_2026-02-22.md`
2. This checklist
- `quantgambit-python/reports/reviewer_checklist_2026-02-22.md`
3. Required raw data slices
- Last 12h trades, decisions, prediction events, order/fill events, and readiness snapshots.
