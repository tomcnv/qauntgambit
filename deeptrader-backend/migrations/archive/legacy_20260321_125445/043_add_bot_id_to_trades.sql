-- Migration: Add bot_id to fast_scalper_trades for bot-level filtering
-- This enables the dashboard to filter trades by bot when viewing bot-specific data

-- Add bot_id column to fast_scalper_trades
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'fast_scalper_trades'
  ) THEN
    ALTER TABLE fast_scalper_trades
      ADD COLUMN IF NOT EXISTS bot_id UUID REFERENCES bot_instances(id);

    -- Create index for efficient bot_id lookups
    CREATE INDEX IF NOT EXISTS idx_fast_scalper_trades_bot_id
      ON fast_scalper_trades(bot_id) WHERE bot_id IS NOT NULL;

    -- Add composite index for user + bot filtering
    CREATE INDEX IF NOT EXISTS idx_fast_scalper_trades_user_bot
      ON fast_scalper_trades(user_id, bot_id, exit_time DESC);

    COMMENT ON COLUMN fast_scalper_trades.bot_id IS 'Bot instance that executed this trade';
  END IF;
END $$;

-- Add bot_id to fast_scalper_positions as well
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'fast_scalper_positions'
  ) THEN
    ALTER TABLE fast_scalper_positions
      ADD COLUMN IF NOT EXISTS bot_id UUID REFERENCES bot_instances(id);

    CREATE INDEX IF NOT EXISTS idx_fast_scalper_positions_bot_id
      ON fast_scalper_positions(bot_id) WHERE bot_id IS NOT NULL;

    COMMENT ON COLUMN fast_scalper_positions.bot_id IS 'Bot instance managing this position';
  END IF;
END $$;
