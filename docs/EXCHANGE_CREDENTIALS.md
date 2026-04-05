# Exchange Credentials & Multi-Exchange Trading

This document describes the per-user exchange credential management system and multi-exchange support in DeepTrader.

## Overview

DeepTrader supports trading on multiple exchanges (OKX, Binance, Bybit) with per-user credential isolation. Each user can:
- Add API credentials for one or more exchanges
- Select which exchange is active for trading
- Choose which tokens/pairs to trade per exchange
- Switch between paper and live trading modes

## Architecture

### Credential Storage

Credentials are stored securely using a two-tier system:

1. **Production (AWS)**: Credentials stored in AWS Secrets Manager with KMS encryption
2. **Development (Local)**: Encrypted JSON files in `.secrets/dev/` directory

Secret IDs follow the pattern: `deeptrader/<environment>/<userId>/<exchange>/<credentialId>` and are passed to the Python bot via `CREDENTIAL_SECRET_ID`. The bot also receives `ACTIVE_EXCHANGE`, `FAST_SCALPER_SYMBOLS`, and environment overrides for local development.

### Database Schema

```sql
-- Credential metadata (not the actual secrets)
user_exchange_credentials (
  id, user_id, exchange, label, secret_id, status,
  last_verified_at, verification_error, permissions, is_testnet
)

-- User's active trading configuration
user_trade_profiles (
  user_id, active_credential_id, active_exchange,
  trading_mode, token_lists, default_max_positions, ...
)

-- Bot pool tracking
bot_pool_assignments (
  user_id, credential_id, bot_id, pool_node, status, ...
)
```

## API Endpoints

### Exchange Credentials

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/exchange-credentials` | List all user credentials |
| POST | `/api/exchange-credentials` | Add new credential |
| PUT | `/api/exchange-credentials/:id` | Update credential metadata |
| PUT | `/api/exchange-credentials/:id/secrets` | Update API keys |
| POST | `/api/exchange-credentials/:id/verify` | Verify credential |
| DELETE | `/api/exchange-credentials/:id` | Delete credential |

### Trade Profile

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/exchange-credentials/profile` | Get user's trade profile |
| PUT | `/api/exchange-credentials/profile/active` | Set active credential |
| PUT | `/api/exchange-credentials/profile/mode` | Set paper/live mode |
| GET | `/api/exchange-credentials/profile/tokens/:exchange` | Get token list |
| PUT | `/api/exchange-credentials/profile/tokens/:exchange` | Update token list |

### Exchange Info

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/exchange-credentials/exchanges` | List supported exchanges |
| GET | `/api/exchange-credentials/exchanges/:exchange/tokens` | Get available tokens |

## Bot Pool Service

The bot pool manages per-user bot instances:

### Local Development
- Spawns Python processes directly
- Injects credentials via environment variables
- Tracks processes by PID

### AWS Production
- Launches ECS Fargate tasks
- Credentials fetched from Secrets Manager by container
- Auto-scaling based on active users

### Bot Lifecycle

```
User requests bot start
  ↓
Check existing bot assignment
  ↓
Fetch user credentials from secrets provider
  ↓
Create bot assignment record
  ↓
Launch bot (local process or ECS task)
  ↓
Inject credentials + token list
  ↓
Bot runs with user-specific config
  ↓
Heartbeat updates to Redis/DB
  ↓
User requests stop → graceful shutdown
```

## Multi-Exchange Support

### Exchange Adaptors

Each exchange has an adaptor implementing `ExchangeAdaptor` interface:

```python
# fast_scalper/exchanges/
├── __init__.py
├── base.py           # Abstract base class
├── factory.py        # Create adaptor by exchange ID
├── okx_adaptor.py    # OKX implementation
├── binance_adaptor.py # Binance implementation
└── bybit_adaptor.py  # Bybit implementation
```

### Common Interface

```python
class ExchangeAdaptor:
    async def connect()
    async def disconnect()
    async def place_order(symbol, side, size, ...)
    async def cancel_order(symbol, order_id)
    async def get_positions()
    async def get_balance()
    async def subscribe_orderbook(symbols, callback)
    # ... etc
```

### Symbol Normalization

Each exchange uses different symbol formats:
- **Internal**: `BTC-USDT-SWAP`
- **OKX**: `BTC-USDT-SWAP`
- **Binance**: `BTC/USDT:USDT`
- **Bybit**: `BTC/USDT:USDT`

Adaptors handle normalization transparently.

## Configuration

### Environment Variables

```bash
# AWS (production)
AWS_REGION=us-east-1
ECS_CLUSTER=deeptrader-bots
ECS_BOT_TASK_DEF=deeptrader-fast-scalper

# Local development
SECRETS_MASTER_PASSWORD=your-dev-password
BOT_POOL_MODE=local  # or 'ecs'

# Active exchange (can be overridden per-user)
ACTIVE_EXCHANGE=okx

# Exchange credentials (legacy single-user mode)
OKX_API_KEY=...
OKX_SECRET_KEY=...
OKX_PASSPHRASE=...
```

## Dashboard UI

Navigate to **Settings > Exchange Connections** to:

1. **Add Exchange**: Enter API credentials for OKX, Binance, or Bybit
2. **Verify**: Test credentials connect successfully
3. **Set Active**: Choose which exchange to trade on
4. **Select Tokens**: Pick trading pairs for the active exchange
5. **Trading Mode**: Toggle between paper and live trading

### Balance Refresh & Trading Capital

1. **Refresh Balance** – Click “Refresh” to fetch the latest exchange equity.  
   - We enforce a short cooldown (30s by default) to avoid rate limits.  
   - Any failures are logged with sanitized metadata and surfaced in the UI.
2. **Set Trading Capital** – Enter the portion of that balance you want the bot to use (must be ≤ fetched balance).  
   - The backend persists the snapshot and redistributes it to the bot pool.  
   - The dashboard highlights when trading capital equals the balance so you can keep a buffer.
3. **Bot Launch** – `botPoolService` injects `TRADING_CAPITAL`, `EXCHANGE_BALANCE`, and the serialized risk profile into every Fast Scalper instance.
4. **Telemetry** – Fast Scalper publishes `trading_capital`, `exchange_balance`, and `capital_utilization_pct` via Redis and Prometheus so dashboards/alerts can warn when utilization > 90% or trading capital exceeds the real balance.

If a refresh fails repeatedly, the credential is marked disconnected and the UI shows the last error. Reconnecting keys or retrying later clears the state automatically.

### Binance Demo & Testnet Notes

- **Spot demo** keys live at `https://demo-api.binance.com` and use the same `/api/v3/*` paths as production. WebSocket trading requests go through `wss://demo-ws-api.binance.com`, while public streams are available at `wss://demo-stream.binance.com`.
- **USDT-M futures demo** keys live at `https://demo-fapi.binance.com` (`/fapi/*` paths). Binance reuses the live futures WebSocket hosts (`wss://fstream.binancefuture.com`) for demo account feeds.
- Binance’s legacy sandbox toggle (`setSandboxMode(true)`) is deprecated for futures. We point ccxt directly at the demo base URLs instead.
- Demo accounts do **not** return balances via the API today. After verification, enter your trading capital manually in the dashboard; it will be persisted per credential.
- FIX API can also be used in demo mode (e.g., `tcp+tls://fix-oe.testnet.binance.vision:9000`). You’ll need to generate an Ed25519 keypair and enable the `FIX_API` permission on the demo API key before connecting.

## Security Considerations

1. **Secrets never logged**: API keys are masked in all logs
2. **Encrypted at rest**: Local dev uses AES-256-GCM, AWS uses KMS
3. **Short TTL cache**: Credentials cached for 5 minutes max
4. **Verification**: Credentials validated before first use
5. **Per-user isolation**: Each user's bot runs with their own credentials

## Troubleshooting

### Credential Verification Fails

1. Check API key permissions on the exchange
2. Ensure IP whitelist includes your server
3. For OKX, verify passphrase is correct
4. Check testnet flag matches your API key type

### Bot Doesn't Start

1. Verify credentials are "verified" status
2. Check bot pool logs: `tail -f /tmp/fast_scalper.log`
3. Ensure Redis is connected
4. Check database for assignment errors

### Tokens Not Showing

1. Verify exchange credentials are verified
2. Check token catalog has been populated
3. Refresh the page after adding credentials

