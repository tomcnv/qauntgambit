# 24h Soundness Audit Report

- Captured at: `2026-02-16T08:37:22.046857+00:00`
- Window start: `2026-02-15T08:37:21.906697+00:00`
- Window end: `2026-02-16T08:37:21.906697+00:00`
- Git commit: `39d76ae131a707257641f294d28454a941c6cb85` on `updates`
- Git dirty: `True`

## Gate Verdict
- `gate_a_net_economics`: **FAIL**
- `gate_b_cost_realism`: **PASS**
- `gate_c_churn`: **FAIL**
- `gate_d_exit_quality`: **FAIL**
- overall: **FAIL**

## Net PnL Decomposition
- `BTCUSDT` closes=105 gross=-116.5784 fees=563.8382 net=-680.4166
- `ETHUSDT` closes=59 gross=169.7142 fees=330.6765 net=-160.9623
- `SOLUSDT` closes=51 gross=100.2888 fees=269.2067 net=-168.9179

## Fill/Churn Matrix
- `BTCUSDT` filled=177 canceled=203 canceled_to_filled=1.1469
- `ETHUSDT` filled=46 canceled=214 canceled_to_filled=4.6522
- `SOLUSDT` filled=44 canceled=214 canceled_to_filled=4.8636
- maker attempts=1442 canceled=631 cancel_rate=43.759% fallback_orders=0

## Expected vs Realized Cost Error
- `BTCUSDT` matched=25 unmatched=0 median_error_bps=-7.572163 p75_error_bps=-3.122182
- `ETHUSDT` matched=37 unmatched=0 median_error_bps=-8.969743 p75_error_bps=-6.510905
- `SOLUSDT` matched=30 unmatched=0 median_error_bps=-7.630324 p75_error_bps=5.466834

## Decision Mix
- `BTCUSDT` accepted=215707 rejected=807057 accept_rate=17.417%
- `ETHUSDT` accepted=91116 rejected=657638 accept_rate=10.849%
- `SOLUSDT` accepted=87902 rejected=533445 accept_rate=12.394%

## Next Action
- Execution-first fixes: reduce cancel/repost churn and forced exits before any signal threshold tuning.

