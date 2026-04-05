# DeepTrader Backend

Backend service for auth, tenant settings, and UI configuration.

Bot runtime APIs now live in the QuantGambit service. Bot/portfolio/trading
endpoints previously served here return HTTP 410 with the QuantGambit API base
in the response payload.

## Features

- **Real-time Market Data**: Binance WebSocket integration for live price feeds
- **Technical Analysis**: RSI, VWAP, EMA, Bollinger Bands, MACD, candlestick patterns
- **News Sentiment**: CryptoPanic and NewsAPI integration with sentiment analysis
- **AI Decision Engine**: DeepSeek V3 (671B parameters) for autonomous trading decisions
- **Paper Trading**: Realistic simulation with slippage and fees
- **Risk Management**: Circuit breakers, loss limits, position sizing
- **WebSocket API**: Real-time updates to frontend
- **REST API**: Auth, settings, and account management

## Installation

```bash
npm install
```

## Configuration

Create a `.env` file (or use the existing one):

```
PORT=3001
DEEPSEEK_API_KEY=your_deepseek_api_key
NEWS_API_KEY=your_newsapi_key
CRYPTOPANIC_API_KEY=your_cryptopanic_key
```

## Running the Server

```bash
# Development (with auto-reload)
npm run dev

# Production
npm start
```

The server will start on `http://localhost:3001`

## API Endpoints

### Bot APIs (moved)

Bot control, portfolio, monitoring, replay, reporting, and trading endpoints
are served by QuantGambit. See its API contract for current routes.

### Activity

- `GET /api/activity?limit=50` - Get activity log

### Health

- `GET /api/health` - Health check

## Architecture

This service now hosts only the dashboard configuration and account management APIs.
Bot runtime, market data, and telemetry streaming are handled by `quantgambit-python`.
- **Emergency Stop**: Immediately close all positions

## Development

The bot uses:
- **Express**: HTTP server
- **ws**: WebSocket server
- **node-cron**: Scheduled tasks
- **technicalindicators**: TA calculations
- **sentiment**: News sentiment analysis
- **axios**: HTTP requests

## Logs

Logs are stored in the `logs/` directory with daily rotation.

## Support

For issues or questions, check the main DeepTrader repository.
