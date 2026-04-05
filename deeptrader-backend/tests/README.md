# API Test Suite

Comprehensive test scripts for all backend APIs.

## Prerequisites

1. Backend server running on `http://localhost:3001`
2. Database with all migrations applied
3. Node.js 18+ (for native fetch support) or install `node-fetch`

## Test Scripts

### 1. Research API Tests (Simple)

Tests the Research & Backtesting APIs:

```bash
# Using Node.js 18+ (native fetch)
node tests/test-research-simple.js

# Or with environment variables
TEST_EMAIL=your@email.com TEST_PASSWORD=yourpassword node tests/test-research-simple.js
```

**Tests:**
- List backtests
- List datasets
- Get backtest detail
- Create backtest
- Filter backtests by status

### 2. Comprehensive API Tests (Bash)

Tests all backend APIs including Research, Settings, Bot Config, and Dashboard:

```bash
./tests/test-all-apis.sh

# Or with environment variables
TEST_EMAIL=your@email.com TEST_PASSWORD=yourpassword ./tests/test-all-apis.sh
```

**Tests:**
- Research & Backtesting APIs
- Settings APIs (Trading, Signal Config, Allocator)
- Bot Config APIs (Profiles, Strategies)
- Dashboard APIs (State, Trading, Signals, Market Context)

### 3. Research API Tests (Advanced)

More detailed tests with better error handling:

```bash
node tests/test-research-apis.js

# With custom token
node tests/test-research-apis.js --token <your_jwt_token>
```

## Test Coverage

### Research & Backtesting
- ✅ List backtests (with pagination and filtering)
- ✅ Get backtest details (with trades and equity curve)
- ✅ Create new backtest
- ✅ List available datasets
- ✅ Error handling (invalid IDs, missing fields)

### Settings
- ✅ Trading settings (GET/PUT)
- ✅ Order types
- ✅ Signal configuration
- ✅ Allocator configuration

### Bot Config
- ✅ Bot profiles (list, create, get)
- ✅ Bot versions
- ✅ Strategies (list, get)

### Dashboard
- ✅ Dashboard state
- ✅ Trading snapshot
- ✅ Signal snapshot
- ✅ Market context

## Expected Results

All tests should return:
- ✅ Green checkmarks for passed tests
- ❌ Red X for failed tests
- Summary with pass/fail counts

## Troubleshooting

### Authentication Fails
- Make sure you have a user account
- The script will attempt to register if login fails
- Or provide a valid JWT token via `--token` flag

### Server Not Running
```bash
cd deeptrader-backend
node server.js
```

### Database Errors
Make sure all migrations are applied:
```bash
# Check if backtest tables exist
psql -d your_database -c "\dt backtest*"
```

### Port Already in Use
Change the port in `server.js` or kill the existing process:
```bash
lsof -ti:3001 | xargs kill
```

## Continuous Integration

These tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions
- name: Run API Tests
  run: |
    npm start &
    sleep 5
    ./tests/test-all-apis.sh
```

## Manual Testing

For manual testing, use curl:

```bash
# Get token
TOKEN=$(curl -X POST http://localhost:3001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"test123"}' \
  | jq -r '.token')

# List backtests
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:3001/api/research/backtests

# Create backtest
curl -X POST http://localhost:3001/api/research/backtests \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_id": "amt_value_area_rejection_scalp",
    "symbol": "BTC-USDT-SWAP",
    "start_date": "2025-01-01T00:00:00Z",
    "end_date": "2025-01-08T00:00:00Z"
  }'
```





