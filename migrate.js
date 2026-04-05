/**
 * Database Migration Script
 * Applies pending migrations to the database
 */

import fs from 'fs';
import path from 'path';
import pool from './deeptrader-backend/config/database.js';

async function runMigration() {
  try {
    console.log('🔍 Checking existing tables...');

    // Check which tables already exist
    const existingTables = await pool.query(`
      SELECT tablename
      FROM pg_tables
      WHERE schemaname = 'public'
    `);

    const tableNames = existingTables.rows.map(row => row.tablename);
    console.log('📋 Existing tables:', tableNames);

    const tablesToCreate = ['orders', 'equity_curves', 'alerts', 'trading_decisions', 'user_trading_settings'];

    for (const tableName of tablesToCreate) {
      if (tableNames.includes(tableName)) {
        console.log(`⏭️  Table '${tableName}' already exists, skipping...`);
        continue;
      }

      console.log(`📝 Creating table '${tableName}'...`);

      let sql = '';
      switch (tableName) {
        case 'orders':
          sql = `
            CREATE TABLE orders (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
                symbol VARCHAR(20) NOT NULL,
                order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('market', 'limit', 'stop_loss', 'stop_limit', 'trailing_stop', 'take_profit', 'bracket', 'oco')),
                side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
                quantity NUMERIC(18,8) NOT NULL CHECK (quantity > 0),
                price NUMERIC(18,8) NULL,
                stop_price NUMERIC(18,8) NULL,
                trailing_percent NUMERIC(5,2) NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'filled', 'cancelled', 'expired', 'rejected')),
                filled_quantity NUMERIC(18,8) DEFAULT 0 CHECK (filled_quantity >= 0),
                avg_fill_price NUMERIC(18,8) NULL,
                time_in_force VARCHAR(10) DEFAULT 'GTC' CHECK (time_in_force IN ('GTC', 'IOC', 'FOK', 'GTD')),
                post_only BOOLEAN DEFAULT FALSE,
                reduce_only BOOLEAN DEFAULT FALSE,
                linked_orders JSONB NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                filled_at TIMESTAMP WITH TIME ZONE NULL,
                expires_at TIMESTAMP WITH TIME ZONE NULL,
                exchange VARCHAR(20) DEFAULT 'binance',
                exchange_order_id VARCHAR(100) NULL,
                error_message TEXT NULL,
                metadata JSONB NULL
            );
          `;
          break;

        case 'equity_curves':
          sql = `
            CREATE TABLE equity_curves (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                equity NUMERIC(18,8) NOT NULL,
                pnl NUMERIC(18,8) NOT NULL DEFAULT 0,
                pnl_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
                UNIQUE(portfolio_id, timestamp)
            );
          `;
          break;

        case 'alerts':
          sql = `
            CREATE TABLE alerts (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                portfolio_id UUID NULL REFERENCES portfolios(id) ON DELETE CASCADE,
                type VARCHAR(50) NOT NULL,
                symbol VARCHAR(20) NULL,
                title VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                severity VARCHAR(20) DEFAULT 'info' CHECK (severity IN ('info', 'warning', 'error', 'critical')),
                is_read BOOLEAN DEFAULT FALSE,
                metadata JSONB NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
          `;
          break;

        case 'trading_decisions':
          sql = `
            CREATE TABLE trading_decisions (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
                token VARCHAR(20) NOT NULL,
                decision JSONB NOT NULL,
                market_data JSONB NOT NULL,
                multi_timeframe JSONB,
                confidence DECIMAL(5,4),
                action VARCHAR(10) NOT NULL CHECK (action IN ('buy', 'sell', 'hold')),
                executed BOOLEAN DEFAULT FALSE,
                order_id UUID REFERENCES orders(id),
                reasoning TEXT,
                factors JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
          `;
          break;

        case 'user_trading_settings':
          sql = `
            CREATE TABLE user_trading_settings (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                enabled_order_types TEXT[] NOT NULL DEFAULT ARRAY['bracket'],
                order_type_settings JSONB NOT NULL,
                risk_profile VARCHAR(20) DEFAULT 'moderate',
                max_concurrent_positions INTEGER DEFAULT 4,
                max_position_size_percent DECIMAL(10,4) DEFAULT 0.10,
                max_total_exposure_percent DECIMAL(10,4) DEFAULT 0.40,
                ai_confidence_threshold DECIMAL(3,1) DEFAULT 7.0,
                trading_interval INTEGER DEFAULT 300000,
                enabled_tokens TEXT[] DEFAULT ARRAY['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'TAOUSDT'],
                day_trading_enabled BOOLEAN DEFAULT FALSE,
                scalping_mode BOOLEAN DEFAULT FALSE,
                trailing_stops_enabled BOOLEAN DEFAULT TRUE,
                partial_profits_enabled BOOLEAN DEFAULT TRUE,
                time_based_exits_enabled BOOLEAN DEFAULT TRUE,
                multi_timeframe_confirmation BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id)
            );
          `;
          break;
      }

      await pool.query(sql);
      console.log(`✅ Created table '${tableName}'`);
    }

    // Create indexes
    console.log('📝 Creating indexes...');
    const indexes = [
      "CREATE INDEX IF NOT EXISTS idx_orders_user_status ON orders(user_id, status)",
      "CREATE INDEX IF NOT EXISTS idx_orders_symbol_status ON orders(symbol, status)",
      "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)",
      "CREATE INDEX IF NOT EXISTS idx_orders_portfolio_id ON orders(portfolio_id)",
      "CREATE INDEX IF NOT EXISTS idx_equity_curves_portfolio_timestamp ON equity_curves(portfolio_id, timestamp DESC)",
      "CREATE INDEX IF NOT EXISTS idx_alerts_user_unread ON alerts(user_id, is_read) WHERE is_read = FALSE",
      "CREATE INDEX IF NOT EXISTS idx_trading_decisions_user_token ON trading_decisions(user_id, token)",
      "CREATE INDEX IF NOT EXISTS idx_trading_decisions_created_at ON trading_decisions(created_at DESC)",
      "CREATE INDEX IF NOT EXISTS idx_trading_decisions_action ON trading_decisions(action)",
      "CREATE INDEX IF NOT EXISTS idx_trading_decisions_executed ON trading_decisions(executed)",
      "CREATE INDEX IF NOT EXISTS idx_trading_decisions_portfolio_id ON trading_decisions(portfolio_id)",
      "CREATE INDEX IF NOT EXISTS idx_trading_decisions_confidence ON trading_decisions(confidence) WHERE confidence >= 0.5",
      "CREATE INDEX IF NOT EXISTS idx_user_trading_settings_user_id ON user_trading_settings(user_id)",
      "CREATE INDEX IF NOT EXISTS idx_user_trading_settings_risk_profile ON user_trading_settings(risk_profile)"
    ];

    for (const indexSql of indexes) {
      await pool.query(indexSql);
    }

    console.log('✅ Migration completed successfully!');
  } catch (error) {
    console.error('❌ Migration failed:', error);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

runMigration();
