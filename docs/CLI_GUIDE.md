# DeepTrader CLI Guide

Command-line interface for managing the DeepTrader trading system and executing manual scalp trades.

## Installation

The CLI is already installed! Just make sure you're in the project directory:

```bash
cd /Users/thomas/Documents/GitHub/deeptrader
```

## Quick Start

### Check System Status

```bash
./deeptrader status
```

Shows:
- Control Manager status (running/stopped)
- All active workers and their status
- Worker statistics

### Start Trading

```bash
# Start in paper trading mode (default)
./deeptrader start

# Start in live trading mode
./deeptrader start --mode live

# Start with specific user ID
./deeptrader start --user-id "1e6e2fa1-1645-445a-a13f-76da74af9929"
```

### Stop Trading

```bash
./deeptrader stop
```

### Restart Trading

```bash
./deeptrader restart
```

## Market Analysis

### View Market Regime

```bash
# View all symbols
./deeptrader regime

# View specific symbol
./deeptrader regime --symbol BTCUSDT
```

Shows:
- Current market regime (trending, ranging, volatile, etc.)
- Whether scalping is allowed
- Risk level assessment
- AI reasoning (if available)

### View Recent Signals

```bash
# Show last 10 signals
./deeptrader signals

# Show last 20 signals
./deeptrader signals --count 20
```

Shows:
- Symbol and side (buy/sell)
- Entry price
- Position size
- Timestamp

## Manual Scalp Trading

### Basic Scalp (Auto-Sizing)

```bash
# Buy with auto-calculated position size
./deeptrader scalp BTCUSDT --side buy

# Sell with auto-calculated position size
./deeptrader scalp ETHUSDT --side sell
```

The risk manager will automatically calculate the optimal position size based on:
- Your account balance
- Risk settings
- Current market conditions

### Scalp with Custom Size

```bash
# Buy 0.001 BTC
./deeptrader scalp BTCUSDT --side buy --size 0.001

# Sell 0.1 ETH
./deeptrader scalp ETHUSDT --side sell --size 0.1
```

### Scalp with Stop Loss & Take Profit

```bash
# Buy BTC with stop loss and take profit
./deeptrader scalp BTCUSDT --side buy --stop-loss 88000 --take-profit 92000

# Sell ETH with stop loss
./deeptrader scalp ETHUSDT --side sell --price 2900 --stop-loss 2950
```

### Live Trading Mode

```bash
# Execute in LIVE mode (real money!)
./deeptrader scalp BTCUSDT --side buy --size 0.001 --mode live
```

⚠️ **WARNING**: `--mode live` will execute real trades with real money!

## Monitoring

### Tail Logs

```bash
./deeptrader logs
```

Shows real-time control manager logs. Press `Ctrl+C` to stop.

## Complete Command Reference

### `./deeptrader status`
Show system status (control manager, workers, statistics)

### `./deeptrader start [OPTIONS]`
Start the trading engine

Options:
- `--mode [paper|live]` - Trading mode (default: paper)
- `--user-id TEXT` - User ID (optional)

### `./deeptrader stop`
Stop the trading engine

### `./deeptrader restart`
Restart the trading engine

### `./deeptrader regime [OPTIONS]`
Show current market regime

Options:
- `--symbol TEXT` - Filter by symbol (e.g., BTCUSDT)

### `./deeptrader signals [OPTIONS]`
Show recent trading signals

Options:
- `--count INTEGER` - Number of signals to show (default: 10)

### `./deeptrader scalp SYMBOL [OPTIONS]`
Execute a manual scalp trade

Arguments:
- `SYMBOL` - Trading pair (e.g., BTCUSDT, ETHUSDT)

Options:
- `--side [buy|sell]` - Trade side (REQUIRED)
- `--size FLOAT` - Position size (optional, auto-calculated if not provided)
- `--price FLOAT` - Entry price (optional, uses market price if not provided)
- `--stop-loss FLOAT` - Stop loss price (optional)
- `--take-profit FLOAT` - Take profit price (optional)
- `--mode [paper|live]` - Trading mode (default: paper)

### `./deeptrader logs`
Tail the control manager logs in real-time

## Examples

### Example 1: Quick Paper Trade

```bash
# Check if system is running
./deeptrader status

# Start if not running
./deeptrader start

# Check market regime
./deeptrader regime --symbol BTCUSDT

# Execute a paper scalp
./deeptrader scalp BTCUSDT --side buy --size 0.001

# Check if signal was generated
./deeptrader signals --count 5
```

### Example 2: Monitored Trading Session

```bash
# Terminal 1: Start trading
./deeptrader start

# Terminal 2: Monitor logs
./deeptrader logs

# Terminal 3: Execute trades and check status
./deeptrader scalp ETHUSDT --side buy --size 0.05
./deeptrader signals
./deeptrader status
```

### Example 3: Conservative Live Trading

```bash
# Check regime first
./deeptrader regime

# Only trade if scalping is allowed
# Execute small live trade with tight stop
./deeptrader scalp BTCUSDT --side buy --size 0.0001 --stop-loss 89000 --mode live

# Monitor immediately
./deeptrader signals
```

## Tips & Best Practices

### 1. Always Check Status First
```bash
./deeptrader status
```
Make sure the control manager and workers are running before trading.

### 2. Check Market Regime
```bash
./deeptrader regime
```
Only scalp when the regime shows "Scalping: ✅ Allowed"

### 3. Start with Paper Trading
Always test your strategy in paper mode first:
```bash
./deeptrader scalp BTCUSDT --side buy --mode paper
```

### 4. Use Auto-Sizing
Let the risk manager calculate position size:
```bash
./deeptrader scalp BTCUSDT --side buy
# No --size parameter = auto-calculated
```

### 5. Monitor Your Trades
```bash
# Check recent signals
./deeptrader signals

# Watch logs in real-time
./deeptrader logs
```

### 6. Set Stop Losses
Always use stop losses for risk management:
```bash
./deeptrader scalp BTCUSDT --side buy --stop-loss 88000
```

## Troubleshooting

### "Control Manager: NOT RUNNING"

Start the system first:
```bash
cd /Users/thomas/Documents/GitHub/deeptrader
npm start
```

Then start trading:
```bash
./deeptrader start
```

### "No recent signals found"

The strategy worker may not have generated signals yet. Check:
1. Market regime allows scalping: `./deeptrader regime`
2. Workers are running: `./deeptrader status`
3. Market conditions are favorable (wait 2-5 minutes)

### Manual Scalp Not Executing

Check the logs:
```bash
./deeptrader logs
```

Common issues:
- Risk manager rejected the trade (too large, violates limits)
- Market conditions unfavorable
- Exchange connectivity issues

## Safety Features

### Paper Trading Default
All commands default to paper trading mode unless you explicitly specify `--mode live`.

### Risk Manager Approval
All trades (manual and automatic) go through the risk manager for approval.

### Stop Loss Protection
You can always add stop losses to limit downside risk.

### Position Size Limits
The risk manager enforces maximum position size limits based on your account balance.

## Advanced Usage

### Scripting

You can use the CLI in bash scripts:

```bash
#!/bin/bash
# Auto-scalp script

# Check if scalping is allowed
REGIME=$(./deeptrader regime --symbol BTCUSDT | grep "Scalping: ✅")

if [ ! -z "$REGIME" ]; then
    echo "Scalping allowed, executing trade..."
    ./deeptrader scalp BTCUSDT --side buy --size 0.001
else
    echo "Scalping not allowed, skipping trade"
fi
```

### Cron Jobs

Schedule regular checks:

```bash
# Check status every hour
0 * * * * cd /Users/thomas/Documents/GitHub/deeptrader && ./deeptrader status >> /tmp/deeptrader_status.log
```

## Getting Help

For any command, use `--help`:

```bash
./deeptrader --help
./deeptrader scalp --help
./deeptrader start --help
```

## Support

For issues or questions:
1. Check the logs: `./deeptrader logs`
2. Check system status: `./deeptrader status`
3. Review the main documentation in the project README

