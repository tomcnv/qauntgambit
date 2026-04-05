# Backtesting Module

This module provides tools for backtesting trading strategies and optimizing parameters.

## Components

### Snapshot Exporter
Export feature snapshots from Redis to JSONL files for replay.

```bash
python -m quantgambit.backtesting.cli export \
  --symbol BTC-USDT-SWAP \
  --start 2024-01-01 \
  --end 2024-01-31 \
  --output snapshots.jsonl
```

### Replay Worker
Replay historical snapshots through the decision engine.

```bash
python -m quantgambit.backtesting.cli replay \
  --input snapshots.jsonl \
  --simulate \
  --fee-bps 1.0 \
  --output results.json
```

### EV Threshold Sweep
Find optimal EV_Min threshold by sweeping values.

```bash
python -m quantgambit.backtesting.cli sweep \
  --input trades.jsonl \
  --min-trades-per-day 5 \
  --output sweep_results.json
```

### Walk-Forward Validation
Validate threshold stability across time periods.

```bash
python -m quantgambit.backtesting.cli validate \
  --input trades.jsonl \
  --n-folds 5 \
  --output validation_results.json
```

## JSONL Formats

### Feature Snapshot Format (for replay)

Each line is a JSON object with:

```json
{
  "symbol": "BTC-USDT-SWAP",
  "timestamp": 1705000000.0,
  "market_context": {
    "price": 42000.0,
    "bid": 41999.0,
    "ask": 42001.0,
    "spread_bps": 0.5,
    "bid_depth_usd": 50000.0,
    "ask_depth_usd": 50000.0
  },
  "features": {
    "confidence": 0.75,
    "stop_loss": 41500.0,
    "take_profit": 42500.0,
    "volatility_regime": "normal",
    "atr_5m": 50.0
  },
  "warmup_ready": true
}
```

**Required fields:**
- `symbol`: Trading pair (e.g., "BTC-USDT-SWAP")
- `timestamp`: Unix timestamp (seconds)

**market_context fields:**
- `price`: Current price
- `bid`, `ask`: Best bid/ask prices
- `spread_bps`: Spread in basis points
- `bid_depth_usd`, `ask_depth_usd`: Order book depth

**features fields:**
- `confidence`: Model confidence (0-1)
- `stop_loss`, `take_profit`: Price levels
- `volatility_regime`: "low", "normal", or "high"

### Trade Format (for sweep/validate)

Each line is a JSON object with:

```json
{
  "timestamp": 1705000000.0,
  "symbol": "BTC-USDT-SWAP",
  "ev": 0.025,
  "pnl_bps": 15.5,
  "side": "long",
  "strategy_id": "mean_reversion",
  "profile_id": "aggressive"
}
```

**Required fields:**
- `timestamp`: Unix timestamp
- `symbol`: Trading pair
- `ev`: Expected value at entry
- `pnl_bps`: Realized PnL in basis points

**Optional fields:**
- `side`: "long" or "short"
- `strategy_id`: Strategy identifier
- `profile_id`: Profile identifier

## Python API

### Export Snapshots

```python
from quantgambit.backtesting.snapshot_exporter import export_snapshots
from datetime import datetime
from pathlib import Path

count = await export_snapshots(
    output_path=Path("snapshots.jsonl"),
    symbol="BTC-USDT-SWAP",
    start_time=datetime(2024, 1, 1),
    end_time=datetime(2024, 1, 31),
)
print(f"Exported {count} snapshots")
```

### Run Replay

```python
from quantgambit.backtesting.replay_worker import ReplayWorker, ReplayConfig
from quantgambit.signals.decision_engine import DecisionEngine
from pathlib import Path

config = ReplayConfig(
    input_path=Path("snapshots.jsonl"),
    fee_bps=1.0,
    slippage_bps=0.5,
)
engine = DecisionEngine()
worker = ReplayWorker(engine, config, simulate=True)
results = await worker.run()
report = worker.get_report()
```

### Run EV Sweep

```python
from quantgambit.backtesting.ev_threshold_sweep import EVThresholdSweeper, BacktestTrade

trades = [
    BacktestTrade(timestamp=1705000000, symbol="BTC", ev=0.02, pnl_bps=10),
    BacktestTrade(timestamp=1705000100, symbol="BTC", ev=0.03, pnl_bps=-5),
    # ...
]

sweeper = EVThresholdSweeper(min_trades_per_day=5)
result = sweeper.sweep(trades, trading_days=30.0)
print(f"Optimal EV_Min: {result.optimal_ev_min}")
```

### Run Walk-Forward Validation

```python
from quantgambit.backtesting.ev_threshold_sweep import WalkForwardValidator

validator = WalkForwardValidator(sweeper, n_folds=5)
result = validator.validate(trades)
print(f"Is Robust: {result.is_robust}")
print(f"Threshold Stability: {result.threshold_stability:.1%}")
```
