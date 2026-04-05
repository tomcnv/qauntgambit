# Regime/Profile Audit Report

- Generated (UTC): `2026-02-20T13:33:48.288290+00:00`
- Tenant: `11111111-1111-1111-1111-111111111111`
- Bot: `bf167763-fee1-4f11-ab9a-6fddadf125de`
- Window: last `6.0`h
- Decision samples: `6000`
- Feature samples: `4000`

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

- Decisions in window: `6000`
- Symbols observed: `ETHUSDT`

### Selected Profile Mix

- `BTCUSDT`:
- `ETHUSDT`:
  - `midvol_mean_reversion`: `4335` (72.25%)
  - `range_market_scalp`: `1621` (27.02%)
  - `value_area_rejection`: `44` (0.73%)
- `SOLUSDT`:

### Rejection Reasons

- `BTCUSDT`:
- `ETHUSDT`:
  - `EV_BELOW_MIN`: `5951` (99.18%)
  - `no_signal`: `44` (0.73%)
  - `prediction_blocked`: `5` (0.08%)
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
- Samples: `4000`
- Session mix: `{'us': 4000}`
- Volatility regime mix: `{'normal': 2278, 'low': 1722}`
- Market regime mix: `{'range': 3943, 'chop': 57}`
- Rotation |abs| p50/p90: `0.000` / `1.107`
- ATR ratio p50/p90: `1.280` / `1.339`
- Dist-to-POC bps p50/p90: `20.42` / `53.64`

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
- Snapshot contexts audited: `4000`
- Top profiles by env-eligible rate (rule pass + enabled strategies):
  - `micro_range_mean_reversion`: env-eligible `100.0%`, top1 `29.6%`, avg score `0.607`
  - `midvol_mean_reversion`: env-eligible `100.0%`, top1 `29.3%`, avg score `0.617`
  - `value_area_rejection`: env-eligible `100.0%`, top1 `19.6%`, avg score `0.606`
  - `poc_magnet`: env-eligible `100.0%`, top1 `14.1%`, avg score `0.628`
  - `near_poc_micro_scalp`: env-eligible `100.0%`, top1 `7.5%`, avg score `0.639`
  - `vwap_reversion`: env-eligible `100.0%`, top1 `0.0%`, avg score `0.563`
  - `range_market_scalp`: env-eligible `100.0%`, top1 `0.0%`, avg score `0.557`
  - `trend_continuation_pullback`: env-eligible `100.0%`, top1 `0.0%`, avg score `0.528`
  - `late_trend_exhaustion`: env-eligible `100.0%`, top1 `0.0%`, avg score `0.521`
  - `stop_run_fade`: env-eligible `100.0%`, top1 `0.0%`, avg score `0.518`
- Most env-blocked profiles (pass rules but strategies disabled):
- Most common rule-fail reasons:
  - `required_session_mismatch`: `12000`

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

- ETHUSDT: profile concentration is high (midvol_mean_reversion at 72.25%). Increase profile diversity by loosening at least one non-range profile constraint (session/rotation/value-location) OR reduce range profile score advantage.
