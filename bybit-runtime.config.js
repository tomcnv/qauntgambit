module.exports = {
  apps: [{
    name: 'runtime-bybit-bf167763',
    interpreter: 'python3',
    script: '/Users/thomas/projects/deeptrader/quantgambit-python/quantgambit/runtime/entrypoint.py',
    args: '--tenant-id 11111111-1111-1111-1111-111111111111 --bot-id bf167763-fee1-4f11-ab9a-6fddadf125de',
    cwd: '/Users/thomas/projects/deeptrader/quantgambit-python',
    env: {
      PYTHONPATH: '/Users/thomas/projects/deeptrader/quantgambit-python',
      REDIS_URL: 'redis://localhost:6379',
      BOT_TIMESCALE_URL: 'postgresql://quantgambit:quantgambit_pw@localhost:5433/quantgambit_bot',
      TENANT_ID: '11111111-1111-1111-1111-111111111111',
      BOT_ID: 'bf167763-fee1-4f11-ab9a-6fddadf125de',
      ACTIVE_EXCHANGE: 'bybit',
      TRADING_MODE: 'live',
      EXECUTION_PROVIDER: 'ccxt',
      ORDERBOOK_TESTNET: 'true',
      BYBIT_TESTNET: 'true',
      EXCHANGE_SECRET_ID: 'deeptrader/dev/11111111-1111-1111-1111-111111111111/bybit/fb213790-5ba6-4637-bccc-25e3d68d4c0c',
      PAPER_EQUITY: '50000',
      RISK_PER_TRADE_PCT: '5.0',
      ORDERBOOK_SYMBOLS: 'BTCUSDT,ETHUSDT,SOLUSDT',
      ORDERBOOK_SOURCE: 'external',
      ORDERBOOK_EVENT_STREAM: 'events:orderbook_feed:bybit'
    },
    error_file: '/tmp/runtime-bybit-error.log',
    out_file: '/tmp/runtime-bybit-out.log',
    combine_logs: true,
    max_restarts: 3,
    autorestart: true
  }]
};
