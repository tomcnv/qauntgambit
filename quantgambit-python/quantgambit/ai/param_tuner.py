"""Adaptive Parameter Tuner — analyzes recent trades and suggests param adjustments.

Runs nightly (or on-demand). Pulls recent trade outcomes, builds a summary,
asks the LLM for parameter adjustment suggestions, and writes them to Redis
for optional human review before applying.

Usage: python -m quantgambit.ai.param_tuner
"""

import asyncio
import json
import os
import time
import logging

import asyncpg
import redis.asyncio as redis

from quantgambit.ai import llm_complete

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379")
TUNER_KEY = "ai:param_suggestions:{bot_id}"

SYSTEM_PROMPT = """You are a quantitative trading parameter optimizer.
Given recent trade statistics, suggest specific parameter adjustments.
Return ONLY valid JSON with this format:
{
  "suggestions": [
    {"param": "take_profit_pct", "current": 0.015, "suggested": 0.02, "reason": "brief reason"},
    {"param": "stop_loss_pct", "current": 0.03, "suggested": 0.025, "reason": "brief reason"}
  ],
  "overall_assessment": "one sentence summary",
  "confidence": 0.6
}

Rules:
- Only suggest changes with clear statistical support
- Never suggest more than 5 changes at once
- Keep changes incremental (< 30% adjustment per param)
- confidence: 0-1, how confident you are these changes will help
- If trades are too few (< 10), say so and suggest no changes"""


async def _get_timescale_pool():
    url = os.getenv("TIMESCALE_URL") or (
        f"postgresql://{os.getenv('TIMESCALE_USER', 'quantgambit')}:"
        f"{os.getenv('TIMESCALE_PASSWORD', 'quantgambit')}@"
        f"{os.getenv('TIMESCALE_HOST', 'localhost')}:"
        f"{os.getenv('TIMESCALE_PORT', '5433')}/"
        f"{os.getenv('TIMESCALE_DB', 'quantgambit_bot')}"
    )
    return await asyncpg.create_pool(url)


async def _get_trade_stats(pool, bot_id: str, days: int = 7) -> dict:
    """Pull trade statistics from position_events."""
    rows = await pool.fetch("""
        SELECT symbol, payload
        FROM position_events
        WHERE bot_id = $1
          AND payload->>'event_type' IN ('position_closed', 'closed')
          AND ts > NOW() - INTERVAL '1 day' * $2
        ORDER BY ts DESC
    """, bot_id, days)

    if not rows:
        return {"trade_count": 0, "period_days": days}

    trades = []
    for row in rows:
        p = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        trades.append({
            "symbol": row["symbol"],
            "side": p.get("side", "long"),
            "pnl_pct": p.get("pnl_pct") or p.get("realized_pnl_pct", 0),
            "hold_sec": p.get("hold_time_sec") or p.get("duration_sec", 0),
            "strategy": p.get("strategy_id", "unknown"),
            "close_reason": p.get("close_reason") or p.get("exit_reason", "unknown"),
            "entry_price": p.get("entry_price", 0),
            "exit_price": p.get("exit_price", 0),
        })

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    avg_hold = sum(t["hold_sec"] for t in trades) / len(trades) if trades else 0

    by_strategy = {}
    for t in trades:
        s = t["strategy"]
        if s not in by_strategy:
            by_strategy[s] = {"count": 0, "wins": 0, "total_pnl": 0}
        by_strategy[s]["count"] += 1
        by_strategy[s]["total_pnl"] += t["pnl_pct"]
        if t["pnl_pct"] > 0:
            by_strategy[s]["wins"] += 1

    by_exit = {}
    for t in trades:
        r = t["close_reason"]
        by_exit[r] = by_exit.get(r, 0) + 1

    return {
        "trade_count": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "avg_hold_sec": avg_hold,
        "total_pnl_pct": sum(t["pnl_pct"] for t in trades),
        "by_strategy": by_strategy,
        "by_exit_reason": by_exit,
        "symbols_traded": list(set(t["symbol"] for t in trades)),
        "period_days": days,
    }


async def _get_current_params(bot_id: str) -> dict:
    """Read current params from env."""
    return {
        "take_profit_pct": float(os.getenv("PARAM_MIN_TAKE_PROFIT_BPS", "80")) / 10000,
        "stop_loss_pct": float(os.getenv("PARAM_MIN_STOP_LOSS_BPS", "50")) / 10000,
        "cooldown_global_sec": int(os.getenv("COOLDOWN_GLOBAL_SEC", "120")),
        "cooldown_symbol_sec": int(os.getenv("COOLDOWN_SYMBOL_SEC", "300")),
        "strategy_fee_bps": float(os.getenv("STRATEGY_FEE_BPS", "2.0")),
        "position_guard_max_age_sec": int(os.getenv("POSITION_GUARD_MAX_AGE_SEC", "86400")),
    }


async def suggest_params(bot_id: str = None) -> dict:
    bot_id = bot_id or os.getenv("BOT_ID", "")
    if not bot_id:
        logger.error("BOT_ID required")
        return {}

    pool = await _get_timescale_pool()
    try:
        stats = await _get_trade_stats(pool, bot_id)
        if stats["trade_count"] == 0:
            logger.info("no_trades_for_tuning bot_id=%s", bot_id[:8])
            return {}
        current = await _get_current_params(bot_id)

        prompt = f"""Recent trading performance ({stats['period_days']} days):
- Total trades: {stats['trade_count']}
- Win rate: {stats.get('win_rate', 0):.1%}
- Avg win: {stats.get('avg_win_pct', 0):.2f}% | Avg loss: {stats.get('avg_loss_pct', 0):.2f}%
- Total PnL: {stats.get('total_pnl_pct', 0):.2f}%
- Avg hold time: {stats.get('avg_hold_sec', 0):.0f}s
- Exit reasons: {json.dumps(stats.get('by_exit_reason', {}))}
- By strategy: {json.dumps(stats.get('by_strategy', {}))}

Current parameters:
{json.dumps(current, indent=2)}

Suggest parameter adjustments:"""

        response = await llm_complete(prompt, system=SYSTEM_PROMPT, temperature=0.3, max_tokens=512)
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            suggestions = json.loads(response[start:end])
        else:
            suggestions = {"suggestions": [], "overall_assessment": "Could not parse LLM response", "confidence": 0}

        # Publish to Redis for review
        r = redis.from_url(REDIS_URL)
        try:
            payload = {
                "bot_id": bot_id,
                "timestamp": time.time(),
                "stats": stats,
                "current_params": current,
                "suggestions": suggestions,
            }
            await r.set(TUNER_KEY.format(bot_id=bot_id), json.dumps(payload, default=str), ex=86400)
            logger.info("param_suggestions_published bot=%s trades=%d suggestions=%d",
                       bot_id[:8], stats["trade_count"], len(suggestions.get("suggestions", [])))
        finally:
            await r.aclose()

        return suggestions
    finally:
        await pool.close()


if __name__ == "__main__":
    result = asyncio.run(suggest_params())
    print(json.dumps(result, indent=2))
