"""AI Trade Journal — generates LLM-powered post-trade reviews.

Runs periodically, finds closed positions without a journal entry,
builds context from DB, and asks the LLM for analysis.

Usage: python -m quantgambit.ai.trade_journal
"""

import asyncio
import json
import os
import logging
from datetime import datetime, timezone

import asyncpg

from quantgambit.ai import llm_complete

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a crypto trading analyst reviewing completed trades.
Given the trade context, write a concise review (3-5 bullet points) covering:
1. Entry quality — was the setup good given market conditions?
2. Exit quality — did it hit TP/SL or time out? Was the exit optimal?
3. What the model predicted vs what happened
4. One actionable lesson for future trades
Keep it under 150 words. Be direct and honest about mistakes."""


async def _get_timescale_pool():
    url = os.getenv("TIMESCALE_URL") or (
        f"postgresql://{os.getenv('TIMESCALE_USER', 'quantgambit')}:"
        f"{os.getenv('TIMESCALE_PASSWORD', 'quantgambit')}@"
        f"{os.getenv('TIMESCALE_HOST', 'localhost')}:"
        f"{os.getenv('TIMESCALE_PORT', '5433')}/"
        f"{os.getenv('TIMESCALE_DB', 'quantgambit_bot')}"
    )
    return await asyncpg.create_pool(url)


async def _get_unjournaled_trades(pool, bot_id: str, limit: int = 5):
    """Find recent closed positions that don't have a journal entry yet."""
    rows = await pool.fetch("""
        SELECT pe.ts, pe.symbol, pe.payload
        FROM position_events pe
        WHERE pe.bot_id = $1
          AND pe.payload->>'event_type' IN ('position_closed', 'closed')
          AND pe.ts > NOW() - INTERVAL '7 days'
          AND NOT EXISTS (
            SELECT 1 FROM trade_journal tj
            WHERE tj.bot_id = $1 AND tj.symbol = pe.symbol
              AND tj.closed_at = pe.ts
          )
        ORDER BY pe.ts DESC
        LIMIT $2
    """, bot_id, limit)
    return rows


async def _ensure_journal_table(pool):
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal (
            id SERIAL PRIMARY KEY,
            bot_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            closed_at TIMESTAMPTZ NOT NULL,
            entry_price DOUBLE PRECISION,
            exit_price DOUBLE PRECISION,
            side TEXT,
            pnl_pct DOUBLE PRECISION,
            strategy TEXT,
            review TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(bot_id, symbol, closed_at)
        )
    """)


async def _journal_trade(pool, bot_id: str, symbol: str, closed_at, payload: dict):
    """Generate and store a journal entry for one trade."""
    entry_price = payload.get("entry_price") or payload.get("avg_entry_price", 0)
    exit_price = payload.get("exit_price") or payload.get("avg_exit_price", 0)
    side = payload.get("side", "long")
    pnl_pct = payload.get("pnl_pct") or payload.get("realized_pnl_pct", 0)
    strategy = payload.get("strategy_id") or payload.get("strategy", "unknown")
    reason = payload.get("close_reason") or payload.get("exit_reason", "unknown")
    prediction = payload.get("prediction_direction") or payload.get("prediction", {}).get("direction", "unknown")
    confidence = payload.get("prediction_confidence") or payload.get("prediction", {}).get("confidence", 0)
    hold_sec = payload.get("hold_time_sec") or payload.get("duration_sec", 0)

    prompt = f"""Trade closed on {symbol}:
- Side: {side} | Strategy: {strategy}
- Entry: {entry_price} → Exit: {exit_price} | PnL: {pnl_pct:.2f}%
- Hold time: {hold_sec:.0f}s | Close reason: {reason}
- Model prediction: {prediction} (confidence: {confidence:.1%})
- Market context at entry: {json.dumps({k: payload[k] for k in ('position_in_value', 'distance_to_poc_bps', 'trend_direction', 'volatility_regime', 'spread_bps') if k in payload}, default=str)}

Review this trade:"""

    try:
        review = await llm_complete(prompt, system=SYSTEM_PROMPT, temperature=0.4)
        await pool.execute("""
            INSERT INTO trade_journal (bot_id, symbol, closed_at, entry_price, exit_price, side, pnl_pct, strategy, review)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (bot_id, symbol, closed_at) DO NOTHING
        """, bot_id, symbol, closed_at, entry_price, exit_price, side, pnl_pct, strategy, review)
        logger.info("journal_entry_created symbol=%s pnl=%.2f%% strategy=%s", symbol, pnl_pct, strategy)
        return review
    except Exception as e:
        logger.error("journal_entry_failed symbol=%s error=%s", symbol, e)
        return None


async def run_journal(bot_id: str = None):
    bot_id = bot_id or os.getenv("BOT_ID", "")
    if not bot_id:
        logger.error("BOT_ID required")
        return

    pool = await _get_timescale_pool()
    try:
        await _ensure_journal_table(pool)
        trades = await _get_unjournaled_trades(pool, bot_id)
        if not trades:
            logger.info("no_unjournaled_trades bot_id=%s", bot_id[:8])
            return
        logger.info("found %d unjournaled trades", len(trades))
        for row in trades:
            payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            await _journal_trade(pool, bot_id, row["symbol"], row["ts"], payload)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run_journal())
