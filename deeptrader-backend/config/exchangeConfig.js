/**
 * Exchange Configuration
 * API keys and settings for supported exchanges
 */

export const EXCHANGE_CONFIG = {
  binance: {
    apiKey: process.env.BINANCE_API_KEY,
    secret: process.env.BINANCE_SECRET,
    testnet: process.env.BINANCE_TESTNET === 'true',
    orderTypes: ['market', 'limit', 'stop_loss', 'stop_limit', 'trailing_stop_market'],
    fees: { maker: 0.001, taker: 0.001 },
    rateLimit: 1200, // requests per minute
    enabled: true
  },
  okx: {
    apiKey: process.env.OKX_API_KEY,
    secret: process.env.OKX_SECRET,
    password: process.env.OKX_PASSWORD,
    testnet: process.env.OKX_TESTNET === 'true',
    orderTypes: ['market', 'limit', 'stop', 'trailing_stop'],
    fees: { maker: 0.0008, taker: 0.001 },
    rateLimit: 300,
    enabled: true
  },
  bybit: {
    apiKey: process.env.BYBIT_API_KEY,
    secret: process.env.BYBIT_SECRET,
    testnet: process.env.BYBIT_TESTNET === 'true',
    orderTypes: ['market', 'limit', 'stop_loss', 'stop_limit'],
    fees: { maker: 0.001, taker: 0.0006 },
    rateLimit: 50,
    enabled: true
  }
};

/**
 * Get enabled exchanges
 */
export function getEnabledExchanges() {
  return Object.entries(EXCHANGE_CONFIG)
    .filter(([_, config]) => config.enabled)
    .map(([name, _]) => name);
}

/**
 * Get exchange config by name
 */
export function getExchangeConfig(exchangeName) {
  return EXCHANGE_CONFIG[exchangeName] || null;
}

/**
 * Validate exchange configuration
 */
export function validateExchangeConfig(exchangeName) {
  const config = EXCHANGE_CONFIG[exchangeName];
  if (!config) {
    throw new Error(`Exchange ${exchangeName} not configured`);
  }

  const requiredFields = ['apiKey', 'secret'];
  if (exchangeName === 'okx') {
    requiredFields.push('password');
  }

  for (const field of requiredFields) {
    if (!config[field]) {
      throw new Error(`${exchangeName} ${field} is not configured`);
    }
  }

  return true;
}




