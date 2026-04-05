# Regime/Profile Audit Report

- Generated (UTC): `2026-02-20T14:07:04.621599+00:00`
- Tenant: `11111111-1111-1111-1111-111111111111`
- Bot: `bf167763-fee1-4f11-ab9a-6fddadf125de`
- Window: last `0.5`h
- Decision samples: `4000`
- Feature samples: `2500`

## Runtime Config Snapshot

- `REDIS_URL`: `redis://localhost:6379`
- `decision_stream`: `events:decisions:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de`
- `feature_stream`: `events:features:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de`
- `DISABLE_STRATEGIES`: ``
- `DISABLE_MEAN_REVERSION_SYMBOLS`: ``
- `PREDICTION_MIN_CONFIDENCE`: ``
- `SESSION_FILTER_ENFORCE_PREFERENCES`: ``
- `SESSION_FILTER_ENFORCE_STRATEGY_SESSIONS`: ``
- `ALLOW_NEAR_POC_ENTRIES`: ``
- `TRADING_DISABLED`: ``

## Decision Stream Summary

- Decisions in window: `4000`
- Symbols observed: `ETHUSDT`

### Selected Profile Mix

- `BTCUSDT`:
- `ETHUSDT`:
  - `value_area_rejection`: `2178` (54.45%)
  - `near_poc_micro_scalp`: `801` (20.03%)
  - `midvol_mean_reversion`: `707` (17.68%)
  - `poc_magnet`: `244` (6.1%)
  - `default`: `66` (1.65%)
  - `range_market_scalp`: `4` (0.1%)
- `SOLUSDT`:

### Rejection Reasons

- `BTCUSDT`:
- `ETHUSDT`:
  - `no_signal`: `3289` (82.23%)
  - `EV_BELOW_MIN`: `630` (15.75%)
  - `none`: `30` (0.75%)
  - `flow_not_negative_for_short (flow=2.31>-0.5)`: `6` (0.15%)
  - `flow_not_negative_for_short (flow=2.08>-0.5)`: `4` (0.1%)
  - `flow_not_negative_for_short (flow=2.07>-0.5)`: `3` (0.07%)
  - `flow_not_negative_for_short (flow=2.09>-0.5)`: `3` (0.07%)
  - `flow_not_negative_for_short (flow=2.10>-0.5)`: `2` (0.05%)
- `SOLUSDT`:

## Feature/Regime Context Summary

### `BTCUSDT`
- Samples: `0`
- Session mix: `{}`
- Volatility regime mix: `{}`
- Market regime mix: `{}`
- Rotation |abs| p50/p90: `0.000` / `0.000`
- ATR ratio p50/p90: `0.000` / `0.000`
- Dist-to-POC bps p50/p90: `0.00` / `0.00`

### `ETHUSDT`
- Samples: `2500`
- Session mix: `{'us': 2500}`
- Volatility regime mix: `{'normal': 2500}`
- Market regime mix: `{'range': 2500}`
- Rotation |abs| p50/p90: `0.500` / `2.445`
- ATR ratio p50/p90: `1.036` / `1.043`
- Dist-to-POC bps p50/p90: `17.25` / `24.18`

### `SOLUSDT`
- Samples: `0`
- Session mix: `{}`
- Volatility regime mix: `{}`
- Market regime mix: `{}`
- Rotation |abs| p50/p90: `0.000` / `0.000`
- ATR ratio p50/p90: `0.000` / `0.000`
- Dist-to-POC bps p50/p90: `0.00` / `0.00`

## Profile Eligibility Audit

### `BTCUSDT`
- Snapshot contexts audited: `0`
- Top profiles by env-eligible rate (rule pass + enabled strategies):
  - `micro_range_mean_reversion`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `early_trend_ignition`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `late_trend_exhaustion`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `stop_run_fade`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `breakout_continuation`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `vwap_reversion`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `spread_compression_scalp`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `vol_expansion_breakout`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `asia_range_scalp`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `europe_open_vol`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
- Most env-blocked profiles (pass rules but strategies disabled):
- Most common rule-fail reasons:

### `ETHUSDT`
- Snapshot contexts audited: `2500`
- Top profiles by env-eligible rate (rule pass + enabled strategies):
  - `value_area_rejection`: env-eligible `97.3%`, top1 `80.3%`, avg score `0.621`
  - `midvol_mean_reversion`: env-eligible `97.3%`, top1 `11.7%`, avg score `0.546`
  - `near_poc_micro_scalp`: env-eligible `97.3%`, top1 `3.9%`, avg score `0.590`
  - `poc_magnet`: env-eligible `97.3%`, top1 `1.4%`, avg score `0.589`
  - `stop_run_fade`: env-eligible `97.3%`, top1 `0.0%`, avg score `0.543`
  - `late_trend_exhaustion`: env-eligible `97.3%`, top1 `0.0%`, avg score `0.541`
  - `micro_range_mean_reversion`: env-eligible `97.3%`, top1 `0.0%`, avg score `0.530`
  - `vwap_reversion`: env-eligible `97.3%`, top1 `0.0%`, avg score `0.529`
  - `us_open_momentum`: env-eligible `97.3%`, top1 `0.0%`, avg score `0.502`
  - `spread_compression_scalp`: env-eligible `97.3%`, top1 `0.0%`, avg score `0.495`
- Most env-blocked profiles (pass rules but strategies disabled):
- Most common rule-fail reasons:
  - `required_session_mismatch`: `7299`
  - `tps_too_low`: `1608`

### `SOLUSDT`
- Snapshot contexts audited: `0`
- Top profiles by env-eligible rate (rule pass + enabled strategies):
  - `micro_range_mean_reversion`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `early_trend_ignition`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `late_trend_exhaustion`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `stop_run_fade`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `breakout_continuation`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `vwap_reversion`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `spread_compression_scalp`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `vol_expansion_breakout`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `asia_range_scalp`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
  - `europe_open_vol`: env-eligible `0.0%`, top1 `0.0%`, avg score `0.000`
- Most env-blocked profiles (pass rules but strategies disabled):
- Most common rule-fail reasons:

## Recommendations

- ETHUSDT: no_signal dominates (82.23%). Focus tuning on entry signal thresholds/prediction calibration before loosening risk gates.
