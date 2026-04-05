/**
 * Deeptrader Backend Server (Core APIs Only)
 */

import express from 'express';
import cors from 'cors';
import { WebSocketServer } from 'ws';
import { healthCheck, testConnection } from './config/database.js';
import { loadLayeredEnv } from './config/env.js';
import authRoutes from './routes/auth.js';
import settingsRoutes from './routes/settings.js';
import promotionsRoutes from './routes/promotions.js';
import auditRoutes from './routes/audit.js';
import exchangeCredentialsRoutes from './routes/exchange-credentials.js';
import userProfileRoutes from './routes/user-profiles.js';
import strategyInstanceRoutes from './routes/strategy-instances.js';
import deploymentRoutes from './routes/deployment.js';
import exchangeAccountsRoutes from './routes/exchange-accounts.js';
import symbolLocksRoutes from './routes/symbol-locks.js';
import configValidationRoutes from './routes/config-validation.js';
import modelsRoutes from './routes/models.js';
import controlRoutes from './routes/control.js';
import botInstanceRoutes from './routes/bot-instances.js';
import { authenticateToken, enforceViewerCoreAccess } from './middleware/auth.js';
import { initializeSecretsProvider } from './services/secretsProvider.js';
import { startRuntimeStreamBridge } from './services/runtimeStreamBridge.js';

loadLayeredEnv();

const IS_TEST_ENV = process.env.NODE_ENV === 'test';
const app = express();
const PORT = process.env.PORT || 3001;
const WS_ENABLED = process.env.WS_ENABLED !== 'false';

const corsOptions = {
  origin: function (origin, callback) {
    if (!origin) return callback(null, true);

    const allowedOrigins = [
      'http://localhost:3000',
      'http://localhost:3001',
      'http://localhost:3002',
      'http://127.0.0.1:3000',
      'http://127.0.0.1:3001',
      'http://127.0.0.1:3002',
      'http://quantgambit.local',
      'http://dashboard.quantgambit.local',
      'http://api.quantgambit.local',
      // Production domains
      'https://quantgambit.com',
      'https://dashboard.quantgambit.com',
      'https://api.quantgambit.com',
      'https://bot.quantgambit.com',
    ];

    if (origin.endsWith('.quantgambit.local') || origin === 'http://quantgambit.local') {
      return callback(null, true);
    }

    // Allow all *.quantgambit.com origins (landing, dashboard, api, bot subdomains).
    if (/^https?:\/\/([a-z0-9-]+\.)*quantgambit\.com$/i.test(origin)) {
      return callback(null, true);
    }

    if (allowedOrigins.includes(origin)) {
      return callback(null, true);
    }

    if (process.env.NODE_ENV !== 'production') {
      return callback(null, true);
    }

    callback(new Error('Not allowed by CORS'));
  },
  credentials: true,
  methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization', 'X-Requested-With'],
};

app.use(cors(corsOptions));
app.use(express.json());
app.use('/api', enforceViewerCoreAccess);

// Core routes used by the dashboard configuration flows
app.use('/api/auth', authRoutes);
app.use('/api/settings', settingsRoutes);
app.use('/api/promotions', promotionsRoutes);
app.use('/api/audit', auditRoutes);
app.use('/api/exchange-credentials', exchangeCredentialsRoutes);
app.use('/api/user-profiles', userProfileRoutes);
app.use('/api/profiles', userProfileRoutes);
app.use('/api/strategy-instances', strategyInstanceRoutes);
app.use('/api/deployment', deploymentRoutes);
app.use('/api/exchange-accounts', exchangeAccountsRoutes);
app.use('/api/symbol-locks', symbolLocksRoutes);
app.use('/api/config-validation', configValidationRoutes);
app.use('/api/models', authenticateToken, modelsRoutes);
app.use('/api/control', controlRoutes);
app.use('/api/bot-instances', botInstanceRoutes);

app.get('/api/health', async (req, res) => {
  try {
    const dbHealth = await healthCheck();
    const ok = dbHealth.status === 'healthy';
    res.json({
      status: ok ? 'ok' : 'degraded',
      timestamp: new Date(),
      database: dbHealth,
    });
  } catch (error) {
    res.status(500).json({
      status: 'error',
      timestamp: new Date(),
      error: error.message,
    });
  }
});

let server = null;
if (!IS_TEST_ENV) {
  initializeSecretsProvider().catch((err) => {
    console.error('❌ Failed to initialize secrets provider:', err.message);
  });

  server = app.listen(PORT, '0.0.0.0', async () => {
    console.log(`🚀 Backend server running on port ${PORT}`);
    console.log(`🔗 Health check: http://localhost:${PORT}/api/health`);

    const dbConnected = await testConnection();
    if (dbConnected) {
      console.log('🗄️ PostgreSQL database connected');
    } else {
      console.error('❌ PostgreSQL database connection failed');
    }
  });
}

if (!IS_TEST_ENV && WS_ENABLED && server) {
  const wss = new WebSocketServer({ server });
  const clients = new Set();

  const broadcast = (payload) => {
    const message = JSON.stringify(payload);
    for (const ws of clients) {
      if (ws.readyState === ws.OPEN) {
        ws.send(message);
      }
    }
  };

  wss.on('connection', (ws) => {
    clients.add(ws);
    ws.on('close', () => clients.delete(ws));
    ws.on('error', () => clients.delete(ws));
  });

  startRuntimeStreamBridge({ broadcast });
}

export default app;
