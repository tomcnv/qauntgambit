// Load environment variables from .env file
require('dotenv').config({ path: __dirname + '/.env' });
const fs = require('fs');

const PROJECT_ROOT = '/Users/thomas/projects/deeptrader';
const QUANT_ROOT = `${PROJECT_ROOT}/quantgambit-python`;

function resolveQuantPython() {
  const candidates = [
    `${QUANT_ROOT}/venv311/bin/python`,
    `${QUANT_ROOT}/venv/bin/python`,
  ];
  const resolved = candidates.find((candidate) => fs.existsSync(candidate));
  if (!resolved) {
    throw new Error('QuantGambit Python runtime not found in quantgambit-python/venv or venv311');
  }
  return resolved;
}

const QUANT_PYTHON = resolveQuantPython();

module.exports = {
  apps: [
    // ═══════════════════════════════════════════════════════════════
    // FRONTEND APPS (for nginx proxy: quantgambit.local)
    // ═══════════════════════════════════════════════════════════════
    
    // Landing Page: quantgambit.local -> port 3000
    {
      name: 'landing',
      script: 'npm',
      args: 'run dev -- --port 3000 --host',
      cwd: '/Users/thomas/projects/deeptrader/deeptrader-landing',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'development'
      },
      error_file: '/tmp/landing-error.log',
      out_file: '/tmp/landing-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true
    },

    // Dashboard: dashboard.quantgambit.local -> port 5173
    {
      name: 'dashboard',
      script: 'npm',
      args: 'run dev -- --port 5173 --host',
      cwd: '/Users/thomas/projects/deeptrader/deeptrader-dashhboard',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'development'
      },
      error_file: '/tmp/dashboard-error.log',
      out_file: '/tmp/dashboard-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true
    },

    // ═══════════════════════════════════════════════════════════════
    // BACKEND API
    // ═══════════════════════════════════════════════════════════════

    // Node.js Backend: api.quantgambit.local -> port 3001
    {
      name: 'deeptrader-backend',
      script: './deeptrader-backend/server.js',
      cwd: '/Users/thomas/projects/deeptrader',
      instances: 1,
      exec_mode: 'fork',  // Use fork mode, not cluster
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000,
      env: {
        NODE_ENV: 'development',
        PORT: 3001,
        ALLOW_UNAUTHENTICATED: 'false',
        DB_HOST: process.env.DB_HOST || process.env.PLATFORM_DB_HOST || 'localhost',
        DB_PORT: process.env.DB_PORT || process.env.PLATFORM_DB_PORT || 5432,
        DB_USER: process.env.PLATFORM_DB_USER || 'platform',
        DB_PASSWORD: process.env.PLATFORM_DB_PASSWORD || 'platform_pw',
        DB_NAME: process.env.PLATFORM_DB_NAME || 'platform_db',
        REDIS_URL: process.env.REDIS_URL || `redis://${process.env.REDIS_HOST || 'localhost'}:${process.env.REDIS_PORT || 6379}`
      },
      error_file: '/tmp/deeptrader-backend-error.log',
      out_file: '/tmp/deeptrader-backend-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 5000
    },

    // QuantGambit Bot API
    {
      name: 'quantgambit-api',
      script: QUANT_PYTHON,
      args: '-m quantgambit.api.app',
      cwd: QUANT_ROOT,
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      // API serves heavy analytics/replay endpoints; 500M causes restart loops.
      max_memory_restart: '6G',
      env: {
        PYTHONPATH: '/Users/thomas/projects/deeptrader/quantgambit-python',
        API_PORT: 3002,
        PYTHONUNBUFFERED: '1',
        AUTH_MODE: process.env.AUTH_MODE || 'jwt',
        AUTH_JWT_SECRET: process.env.AUTH_JWT_SECRET || process.env.JWT_SECRET || 'your-secret-key-change-in-production',
        AUTH_ALLOW_DEV_IDENTITY_FALLBACK: 'false',
        ACTIVE_EXCHANGE: process.env.ACTIVE_EXCHANGE || 'bybit',
        EXCHANGE_SECRET_ID: process.env.EXCHANGE_SECRET_ID || '',
        BYBIT_DEMO: process.env.BYBIT_DEMO || 'false',
        BYBIT_TESTNET: process.env.BYBIT_TESTNET || 'false',
        ORDER_UPDATES_DEMO: process.env.ORDER_UPDATES_DEMO || 'false',
        ORDERBOOK_SYMBOLS: process.env.ORDERBOOK_SYMBOLS || 'BTCUSDT,ETHUSDT,SOLUSDT',
        REDIS_URL: process.env.REDIS_URL || `redis://${process.env.REDIS_HOST || 'localhost'}:${process.env.REDIS_PORT || 6379}`,
        BOT_TIMESCALE_URL: process.env.BOT_TIMESCALE_URL || `postgresql://${process.env.BOT_DB_USER || 'quantgambit'}:${process.env.BOT_DB_PASSWORD || 'quantgambit_pw'}@${process.env.BOT_DB_HOST || 'localhost'}:${process.env.BOT_DB_PORT || 5433}/${process.env.BOT_DB_NAME || 'quantgambit_bot'}`,
        DASHBOARD_DB_HOST: process.env.DASHBOARD_DB_HOST || process.env.DB_HOST || process.env.PLATFORM_DB_HOST || 'localhost',
        DASHBOARD_DB_PORT: process.env.DASHBOARD_DB_PORT || process.env.DB_PORT || process.env.PLATFORM_DB_PORT || '5432',
        DASHBOARD_DB_NAME: process.env.DASHBOARD_DB_NAME || process.env.PLATFORM_DB_NAME || 'platform_db',
        DASHBOARD_DB_USER: process.env.DASHBOARD_DB_USER || process.env.PLATFORM_DB_USER || 'platform',
        DASHBOARD_DB_PASSWORD: process.env.DASHBOARD_DB_PASSWORD || process.env.PLATFORM_DB_PASSWORD || 'platform_pw'
      },
      error_file: '/tmp/quantgambit-api-error.log',
      out_file: '/tmp/quantgambit-api-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 10000
    },

    // ═══════════════════════════════════════════════════════════════
    // MARKET DATA SERVICES
    // NOTE: Each exchange gets its own MDS instance with exchange-specific streams
    // Stream naming convention: events:{type}:{exchange} (e.g., events:trades:binance)
    // 
    // Currently ENABLED: Bybit ONLY (for demo trading)
    // Currently DISABLED: Binance, OKX (see bottom of file for config templates)
    // ═══════════════════════════════════════════════════════════════

    // ═══════════════════════════════════════════════════════════════
    // NOTE: QuantGambit Runtime is NOT auto-started by PM2.
    // It is launched dynamically by the Control Manager when a user
    // starts their bot via the dashboard Run Bar, with the specific
    // tenant_id/bot_id and exchange config provided at launch time.
    // ═══════════════════════════════════════════════════════════════

    // Market Data Service (Bybit) - ACTIVE
    // NOTE: Uses LIVE market data because Bybit Demo trading uses live prices
    // MDS must match execution environment prices to avoid order rejections
    {
      name: 'market-data-service-bybit',
      script: QUANT_PYTHON,
      args: './market-data-service/app.py',
      cwd: PROJECT_ROOT,
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        PYTHONMALLOC: 'malloc',
        PYTHONPATH: '/Users/thomas/projects/deeptrader/quantgambit-python',
        REDIS_URL: process.env.REDIS_URL || `redis://${process.env.REDIS_HOST || 'localhost'}:${process.env.REDIS_PORT || 6379}`,
        EXCHANGE: 'bybit',
        MARKET_TYPE: 'perp',
        SYMBOLS: process.env.SYMBOLS || 'BTCUSDT,ETHUSDT,SOLUSDT',
        TESTNET: 'false',  // Use LIVE data - Bybit Demo uses live prices!
        PUBLISH_MODE: 'both',
        ORDERBOOK_EVENT_STREAM: 'events:orderbook_feed:bybit',
        TRADES_ENABLED: 'true',
        TRADE_EVENT_STREAM: 'events:trades:bybit',
        MARKET_DATA_STREAM: 'events:market_data:bybit',
        PORT: '8083',
        TICKERS_ENABLED: 'false',
        MAX_STREAM_LENGTH: '5000',
        PUBLISH_MAXLEN: '10000',
        BACKPRESSURE_SLEEP_MS: '100',
        SNAPSHOT_INTERVAL_SEC: '30',
        // === WS-first architecture ===
        // Public market data always uses mainnet WS for stability
        USE_MAINNET_PUBLIC_WS: 'true',
        // Trade WS config
        TRADE_WS_MESSAGE_TIMEOUT_SEC: '30',  // Longer timeout - trades can be sparse
        TRADE_WS_STALE_GUARDRAIL_SEC: '60',  // Log stale warnings less frequently
        TRADE_WS_STALE_WATCHDOG_SEC: '45',   // Trigger resync after 45s without trades
        // REST fallback for seeding/gap-fill only (not continuous polling)
        TRADE_REST_FALLBACK_ENABLED: 'true',
        TRADE_REST_FALLBACK_INTERVAL_SEC: '30',  // Only fetch every 30s during gaps
        TRADE_REST_FALLBACK_LIMIT: '10',
        // Orderbook WS config
        ORDERBOOK_WS_RECV_TIMEOUT_SEC: '10',
        ORDERBOOK_WS_HEARTBEAT_SEC: '10',
        BYBIT_ORDERBOOK_INCLUDE_L1: 'true',
        BYBIT_ORDERBOOK_WS_ONLY: 'true',
        ORDERBOOK_WS_ONLY_SNAPSHOT: 'true',
        // === Health & backoff config ===
        MDS_HEALTH_KEY: 'mds:health:bybit',
        TRADE_STALE_SEC: '30',      // Mark trade feed stale after 30s
        ORDERBOOK_STALE_SEC: '30',  // Mark orderbook feed stale after 30s
        BACKOFF_TRIGGER_COUNT: '3', // Enter backoff after 3 failures
        BACKOFF_WINDOW_SEC: '120',  // Within 2 minute window
        BACKOFF_DURATION_SEC: '60', // Stay in backoff for 60s
      },
      error_file: '/tmp/market-data-service-bybit-error.log',
      out_file: '/tmp/market-data-service-bybit-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 10000
    },

    // Market Data Service (Bybit Spot)
    {
      name: 'market-data-service-bybit-spot',
      script: QUANT_PYTHON,
      args: './market-data-service/app.py',
      cwd: PROJECT_ROOT,
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        PYTHONMALLOC: 'malloc',
        PYTHONPATH: '/Users/thomas/projects/deeptrader/quantgambit-python',
        REDIS_URL: process.env.REDIS_URL || `redis://${process.env.REDIS_HOST || 'localhost'}:${process.env.REDIS_PORT || 6379}`,
        EXCHANGE: 'bybit',
        MARKET_TYPE: 'spot',
        SYMBOLS: process.env.SYMBOLS || 'BTCUSDT,ETHUSDT,SOLUSDT',
        TESTNET: 'false',
        PUBLISH_MODE: 'both',
        ORDERBOOK_EVENT_STREAM: 'events:orderbook_feed:bybit:spot',
        TRADES_ENABLED: 'true',
        TRADE_EVENT_STREAM: 'events:trades:bybit:spot',
        MARKET_DATA_STREAM: 'events:market_data:bybit',
        PORT: '8084',
        TICKERS_ENABLED: 'false',
        MAX_STREAM_LENGTH: '5000',
        PUBLISH_MAXLEN: '10000',
        BACKPRESSURE_SLEEP_MS: '100',
        SNAPSHOT_INTERVAL_SEC: '30',
        USE_MAINNET_PUBLIC_WS: 'true',
        TRADE_WS_MESSAGE_TIMEOUT_SEC: '30',
        TRADE_WS_STALE_GUARDRAIL_SEC: '60',
        TRADE_WS_STALE_WATCHDOG_SEC: '45',
        TRADE_REST_FALLBACK_ENABLED: 'true',
        TRADE_REST_FALLBACK_INTERVAL_SEC: '30',
        TRADE_REST_FALLBACK_LIMIT: '10',
        ORDERBOOK_WS_RECV_TIMEOUT_SEC: '10',
        ORDERBOOK_WS_HEARTBEAT_SEC: '10',
        BYBIT_ORDERBOOK_INCLUDE_L1: 'true',
        BYBIT_ORDERBOOK_WS_ONLY: 'true',
        ORDERBOOK_WS_ONLY_SNAPSHOT: 'true',
        MDS_HEALTH_KEY: 'mds:health:bybit:spot',
        TRADE_STALE_SEC: '30',
        ORDERBOOK_STALE_SEC: '30',
        BACKOFF_TRIGGER_COUNT: '3',
        BACKOFF_WINDOW_SEC: '120',
        BACKOFF_DURATION_SEC: '60',
      },
      error_file: '/tmp/market-data-service-bybit-spot-error.log',
      out_file: '/tmp/market-data-service-bybit-spot-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 10000
    },

    // Control Manager (Redis command queue listener - launches runtimes on demand)
    {
      name: 'control-manager',
      script: QUANT_PYTHON,
      args: '-m quantgambit.control.command_manager',
      cwd: QUANT_ROOT,
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '200M',
      env: {
        PYTHONPATH: '/Users/thomas/projects/deeptrader/quantgambit-python',
        REDIS_URL: process.env.REDIS_URL || `redis://${process.env.REDIS_HOST || 'localhost'}:${process.env.REDIS_PORT || 6379}`,
        BOT_TIMESCALE_URL: process.env.BOT_TIMESCALE_URL || `postgresql://${process.env.BOT_DB_USER || 'quantgambit'}:${process.env.BOT_DB_PASSWORD || 'quantgambit_pw'}@${process.env.BOT_DB_HOST || 'localhost'}:${process.env.BOT_DB_PORT || 5433}/${process.env.BOT_DB_NAME || 'quantgambit_bot'}`,
        CONTROL_GROUP: 'quantgambit_control',
        CONTROL_CONSUMER: 'control_manager',
        CONTROL_ENABLE_LAUNCH: 'true',
        CONTROL_REQUIRE_HEALTH: 'false',
        CONTROL_READY_TIMEOUT_SEC: '45',
        CONTROL_STRICT_CONFIG_PARITY: 'true',
        // Dynamic runtime launch/stop scripts - TENANT_ID/BOT_ID passed via env
        RUNTIME_LAUNCH_CMD: '/Users/thomas/projects/deeptrader/scripts/launch-runtime.sh',
        RUNTIME_STOP_CMD: '/Users/thomas/projects/deeptrader/scripts/stop-runtime.sh'
      },
      error_file: '/tmp/control-manager-error.log',
      out_file: '/tmp/control-manager-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 10000
    },

    // Backtest Worker (processes pending backtest jobs)
    {
      name: 'backtest-worker',
      script: QUANT_PYTHON,
      args: '-m quantgambit.backtesting.worker',
      cwd: QUANT_ROOT,
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '2G',  // Increased from 500M - backtesting large datasets needs more memory
      env: {
        PYTHONPATH: '/Users/thomas/projects/deeptrader/quantgambit-python',
        PYTHONUNBUFFERED: '1',
        BACKTEST_POLL_INTERVAL: '5',
        BACKTEST_MAX_CONCURRENT: '2',
        // Platform DB (where backtest_runs table lives)
        DASHBOARD_DB_HOST: process.env.DASHBOARD_DB_HOST || process.env.PLATFORM_DB_HOST || 'localhost',
        DASHBOARD_DB_PORT: process.env.DASHBOARD_DB_PORT || process.env.PLATFORM_DB_PORT || '5432',
        DASHBOARD_DB_NAME: process.env.DASHBOARD_DB_NAME || process.env.PLATFORM_DB_NAME || 'platform_db',
        DASHBOARD_DB_USER: process.env.DASHBOARD_DB_USER || process.env.PLATFORM_DB_USER || 'platform',
        DASHBOARD_DB_PASSWORD: process.env.DASHBOARD_DB_PASSWORD || process.env.PLATFORM_DB_PASSWORD || 'platform_pw',
        // TimescaleDB (where market_candles table lives)
        TIMESCALE_HOST: process.env.BOT_DB_HOST || 'localhost',
        TIMESCALE_PORT: process.env.BOT_DB_PORT || '5433',
        TIMESCALE_DB: process.env.BOT_DB_NAME || 'quantgambit_bot',
        TIMESCALE_USER: process.env.BOT_DB_USER || 'quantgambit',
        TIMESCALE_PASSWORD: process.env.BOT_DB_PASSWORD || ''
      },
      error_file: '/tmp/backtest-worker-error.log',
      out_file: '/tmp/backtest-worker-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 30000
    },

    // ═══════════════════════════════════════════════════════════════
    // DATA PERSISTENCE WORKER
    // Continuously persists orderbook and trade data from Redis to TimescaleDB
    // Runs independently of the trading runtime for continuous data collection
    // ═══════════════════════════════════════════════════════════════

    // AI Sentiment Signal — scrapes news/social, scores with LLM, publishes to Redis
    {
      name: 'ai-sentiment',
      script: QUANT_PYTHON,
      args: '-m quantgambit.ai.sentiment_signal',
      cwd: QUANT_ROOT,
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '200M',
      env: {
        PYTHONPATH: '/Users/thomas/projects/deeptrader/quantgambit-python',
        PYTHONUNBUFFERED: '1',
        REDIS_URL: process.env.REDIS_URL || `redis://${process.env.REDIS_HOST || 'localhost'}:${process.env.REDIS_PORT || 6379}`,
        COPILOT_LLM_API_KEY: process.env.COPILOT_LLM_API_KEY || '',
        COPILOT_LLM_BASE_URL: process.env.COPILOT_LLM_BASE_URL || 'https://api.deepseek.com/v1',
        COPILOT_LLM_MODEL: process.env.COPILOT_LLM_MODEL || 'deepseek-chat',
        SENTIMENT_POLL_SEC: '300',
      },
      error_file: '/tmp/ai-sentiment-error.log',
      out_file: '/tmp/ai-sentiment-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 5000
    },

    {
      name: 'data-persistence-worker',
      script: QUANT_PYTHON,
      args: '-m quantgambit.workers.data_persistence_worker',
      cwd: QUANT_ROOT,
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        PYTHONPATH: '/Users/thomas/projects/deeptrader/quantgambit-python',
        PYTHONUNBUFFERED: '1',
        REDIS_URL: process.env.REDIS_URL || `redis://${process.env.REDIS_HOST || 'localhost'}:${process.env.REDIS_PORT || 6379}`,
        BOT_TIMESCALE_URL: process.env.BOT_TIMESCALE_URL || `postgresql://${process.env.BOT_DB_USER || 'quantgambit'}:${process.env.BOT_DB_PASSWORD || 'quantgambit_pw'}@${process.env.BOT_DB_HOST || 'localhost'}:${process.env.BOT_DB_PORT || 5433}/${process.env.BOT_DB_NAME || 'quantgambit_bot'}`,
        EXCHANGE: 'bybit',
        ORDERBOOK_EVENT_STREAM: 'events:orderbook_feed:bybit',
        TRADE_EVENT_STREAM: 'events:trades:bybit',
        CONSUMER_GROUP: 'data_persistence',
        // Persistence configuration (from .env)
        PERSISTENCE_ORDERBOOK_ENABLED: process.env.PERSISTENCE_ORDERBOOK_ENABLED || 'true',
        PERSISTENCE_ORDERBOOK_INTERVAL_SEC: process.env.PERSISTENCE_ORDERBOOK_INTERVAL_SEC || '1.0',
        PERSISTENCE_ORDERBOOK_BATCH_SIZE: process.env.PERSISTENCE_ORDERBOOK_BATCH_SIZE || '100',
        PERSISTENCE_ORDERBOOK_FLUSH_SEC: process.env.PERSISTENCE_ORDERBOOK_FLUSH_SEC || '5.0',
        PERSISTENCE_TRADES_ENABLED: process.env.PERSISTENCE_TRADES_ENABLED || 'true',
        PERSISTENCE_TRADES_BATCH_SIZE: process.env.PERSISTENCE_TRADES_BATCH_SIZE || '500',
        PERSISTENCE_TRADES_FLUSH_SEC: process.env.PERSISTENCE_TRADES_FLUSH_SEC || '1.0',
        PERSISTENCE_RETRY_MAX_ATTEMPTS: process.env.PERSISTENCE_RETRY_MAX_ATTEMPTS || '3',
        PERSISTENCE_RETRY_BASE_DELAY_SEC: process.env.PERSISTENCE_RETRY_BASE_DELAY_SEC || '0.1'
      },
      error_file: '/tmp/data-persistence-worker-error.log',
      out_file: '/tmp/data-persistence-worker-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 10000
    }
  ]
};

// ═══════════════════════════════════════════════════════════════════════════
// DISABLED MARKET DATA SERVICES
// Uncomment and add to the apps array above to enable
// ═══════════════════════════════════════════════════════════════════════════
/*
    // Market Data Service (OKX) - DISABLED
    {
      name: 'market-data-service-okx',
      script: './quantgambit-python/venv/bin/python',
      args: './market-data-service/app.py',
      cwd: '/Users/thomas/projects/deeptrader',
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        PYTHONPATH: '/Users/thomas/projects/deeptrader/quantgambit-python',
        REDIS_URL: process.env.REDIS_URL || `redis://${process.env.REDIS_HOST || 'localhost'}:${process.env.REDIS_PORT || 6379}`,
        EXCHANGE: 'okx',
        MARKET_TYPE: 'perp',
        SYMBOLS: 'BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP',
        PUBLISH_MODE: 'both',
        ORDERBOOK_EVENT_STREAM: 'events:orderbook_feed:okx',
        TRADES_ENABLED: 'true',
        TRADE_EVENT_STREAM: 'events:trades:okx',
        MARKET_DATA_STREAM: 'events:market_data:okx',
        PORT: '8081',
        TICKERS_ENABLED: 'false',
        MAX_STREAM_LENGTH: '20000',
        PUBLISH_MAXLEN: '10000',
        BACKPRESSURE_SLEEP_MS: '50',
        SNAPSHOT_INTERVAL_SEC: '30',
        TRADE_WS_MESSAGE_TIMEOUT_SEC: '10',
        TRADE_REST_FALLBACK_ENABLED: 'true',
        TRADE_REST_FALLBACK_INTERVAL_SEC: '30',
        TRADE_REST_FALLBACK_LIMIT: '5'
      },
      error_file: '/tmp/market-data-service-okx-error.log',
      out_file: '/tmp/market-data-service-okx-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 10000
    },

    // Market Data Service (Bybit) - DISABLED
    {
      name: 'market-data-service-bybit',
      script: './quantgambit-python/venv/bin/python',
      args: './market-data-service/app.py',
      cwd: '/Users/thomas/projects/deeptrader',
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        PYTHONPATH: '/Users/thomas/projects/deeptrader/quantgambit-python',
        REDIS_URL: process.env.REDIS_URL || `redis://${process.env.REDIS_HOST || 'localhost'}:${process.env.REDIS_PORT || 6379}`,
        EXCHANGE: 'bybit',
        MARKET_TYPE: 'perp',
        SYMBOLS: 'BTCUSDT,ETHUSDT,SOLUSDT',
        PUBLISH_MODE: 'both',
        ORDERBOOK_EVENT_STREAM: 'events:orderbook_feed:bybit',
        TRADES_ENABLED: 'true',
        TRADE_EVENT_STREAM: 'events:trades:bybit',
        MARKET_DATA_STREAM: 'events:market_data:bybit',
        PORT: '8083',
        TICKERS_ENABLED: 'false',
        MAX_STREAM_LENGTH: '20000',
        PUBLISH_MAXLEN: '10000',
        BACKPRESSURE_SLEEP_MS: '50',
        SNAPSHOT_INTERVAL_SEC: '30',
        TRADE_WS_MESSAGE_TIMEOUT_SEC: '10',
        TRADE_REST_FALLBACK_ENABLED: 'true',
        TRADE_REST_FALLBACK_INTERVAL_SEC: '30',
        TRADE_REST_FALLBACK_LIMIT: '5'
      },
      error_file: '/tmp/market-data-service-bybit-error.log',
      out_file: '/tmp/market-data-service-bybit-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 10000
    },
*/
