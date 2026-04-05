# 24h Soundness Audit Report

- Captured at: `2026-02-16T06:23:40.336950+00:00`
- Window start: `2026-02-16T00:23:40.019397+00:00`
- Window end: `2026-02-16T06:23:40.019397+00:00`
- Git commit: `5eeeac1d471adc966f72bd6fc44a718c7a0aeab9` on `percentage-updates`
- Git dirty: `True`

## Gate Verdict
- `gate_a_net_economics`: **FAIL**
- `gate_b_cost_realism`: **PASS**
- `gate_c_churn`: **FAIL**
- `gate_d_exit_quality`: **FAIL**
- overall: **FAIL**

## Net PnL Decomposition
- `BTCUSDT` closes=30 gross=-17.5460 fees=223.9630 net=-241.5089
- `ETHUSDT` closes=37 gross=-20.6055 fees=210.4107 net=-231.0161
- `SOLUSDT` closes=34 gross=-44.8764 fees=181.7154 net=-226.5918

## Fill/Churn Matrix
- `BTCUSDT` filled=15 canceled=181 canceled_to_filled=12.0667
- `ETHUSDT` filled=24 canceled=188 canceled_to_filled=7.8333
- `SOLUSDT` filled=19 canceled=179 canceled_to_filled=9.4211
- maker attempts=909 canceled=548 cancel_rate=60.286% fallback_orders=0

## Expected vs Realized Cost Error
- `BTCUSDT` matched=22 unmatched=0 median_error_bps=-6.067614 p75_error_bps=-3.122182
- `ETHUSDT` matched=25 unmatched=0 median_error_bps=-7.834461 p75_error_bps=1.82244
- `SOLUSDT` matched=24 unmatched=0 median_error_bps=-8.205633 p75_error_bps=3.976458

## Decision Mix
- `BTCUSDT` accepted=54304 rejected=172950 accept_rate=19.287%
- `ETHUSDT` accepted=44234 rejected=181192 accept_rate=16.404%
- `SOLUSDT` accepted=37739 rejected=143098 accept_rate=17.266%

## Next Action
- Execution-first fixes: reduce cancel/repost churn and forced exits before any signal threshold tuning.

