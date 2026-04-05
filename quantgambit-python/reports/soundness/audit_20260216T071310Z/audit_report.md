# 24h Soundness Audit Report

- Captured at: `2026-02-16T07:13:11.221134+00:00`
- Window start: `2026-02-16T05:13:10.886068+00:00`
- Window end: `2026-02-16T07:13:10.886068+00:00`
- Git commit: `5eeeac1d471adc966f72bd6fc44a718c7a0aeab9` on `percentage-updates`
- Git dirty: `True`

## Gate Verdict
- `gate_a_net_economics`: **FAIL**
- `gate_b_cost_realism`: **PASS**
- `gate_c_churn`: **FAIL**
- `gate_d_exit_quality`: **PASS**
- overall: **FAIL**

## Net PnL Decomposition

## Fill/Churn Matrix
- `BTCUSDT` filled=0 canceled=86 canceled_to_filled=inf
- `ETHUSDT` filled=0 canceled=72 canceled_to_filled=inf
- `SOLUSDT` filled=0 canceled=60 canceled_to_filled=inf
- maker attempts=219 canceled=218 cancel_rate=99.543% fallback_orders=0

## Expected vs Realized Cost Error

## Decision Mix
- `BTCUSDT` accepted=16109 rejected=49630 accept_rate=19.681%
- `ETHUSDT` accepted=20305 rejected=42276 accept_rate=24.498%
- `SOLUSDT` accepted=14501 rejected=42186 accept_rate=20.370%

## Next Action
- Execution-first fixes: reduce cancel/repost churn and forced exits before any signal threshold tuning.

