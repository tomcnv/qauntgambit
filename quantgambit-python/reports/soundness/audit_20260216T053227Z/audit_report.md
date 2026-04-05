# 24h Soundness Audit Report

- Captured at: `2026-02-16T05:32:28.318111+00:00`
- Window start: `2026-02-15T05:32:27.646323+00:00`
- Window end: `2026-02-16T05:32:27.646323+00:00`
- Git commit: `5eeeac1d471adc966f72bd6fc44a718c7a0aeab9` on `percentage-updates`
- Git dirty: `True`

## Gate Verdict
- `gate_a_net_economics`: **FAIL**
- `gate_b_cost_realism`: **PASS**
- `gate_c_churn`: **PASS**
- `gate_d_exit_quality`: **FAIL**
- overall: **FAIL**

## Net PnL Decomposition
- `BTCUSDT` closes=109 gross=-103.2298 fees=578.4447 net=-681.6745
- `ETHUSDT` closes=74 gross=269.0393 fees=389.6149 net=-120.5755
- `SOLUSDT` closes=65 gross=248.8427 fees=343.3066 net=-94.4639

## Fill/Churn Matrix
- `BTCUSDT` filled=211 canceled=143 canceled_to_filled=0.6777
- `ETHUSDT` filled=62 canceled=163 canceled_to_filled=2.6290
- `SOLUSDT` filled=70 canceled=161 canceled_to_filled=2.3000
- maker attempts=1280 canceled=467 cancel_rate=36.484% fallback_orders=0

## Expected vs Realized Cost Error
- `BTCUSDT` matched=25 unmatched=0 median_error_bps=-7.572163 p75_error_bps=-3.122182
- `ETHUSDT` matched=37 unmatched=0 median_error_bps=-8.969743 p75_error_bps=-6.510905
- `SOLUSDT` matched=28 unmatched=0 median_error_bps=-8.205633 p75_error_bps=5.466834

## Decision Mix
- `BTCUSDT` accepted=213494 rejected=853609 accept_rate=16.671%
- `ETHUSDT` accepted=84805 rejected=709594 accept_rate=9.645%
- `SOLUSDT` accepted=91230 rejected=576164 accept_rate=12.025%

## Next Action
- Execution-first fixes: reduce cancel/repost churn and forced exits before any signal threshold tuning.

