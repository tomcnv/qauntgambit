"""Standalone candle worker for debugging/troubleshooting.

Usage:
  REDIS_URL=redis://localhost:6379 \
  TENANT_ID=<tenant> BOT_ID=<bot> EXCHANGE=binance \
  CANDLE_SOURCE_STREAM=events:trades:binance \
  CANDLE_STREAM=events:candles:<tenant>:<bot> \
  ./venv311/bin/python -m quantgambit.scripts.run_candle_worker
"""

from __future__ import annotations

import asyncio
import os
import sys

import redis.asyncio as redis

from quantgambit.ingest.candle_worker import CandleWorker, CandleWorkerConfig
from quantgambit.observability.logger import configure_logging, log_info
from quantgambit.storage.redis_streams import RedisStreamsClient
from quantgambit.storage.timescale import NullTimescaleWriter


async def _main() -> None:
    configure_logging()
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    tenant_id = os.getenv("TENANT_ID")
    bot_id = os.getenv("BOT_ID")
    exchange = os.getenv("EXCHANGE", os.getenv("ACTIVE_EXCHANGE", "binance"))

    if not tenant_id or not bot_id:
        sys.exit("TENANT_ID and BOT_ID are required to run the candle worker.")

    source_stream = os.getenv(
        "CANDLE_SOURCE_STREAM",
        os.getenv("TRADE_STREAM", "events:trades:binance"),
    )
    output_stream = os.getenv(
        "CANDLE_STREAM",
        f"events:candles:{tenant_id}:{bot_id}",
    )
    consumer_group = os.getenv(
        "CANDLE_CONSUMER_GROUP",
        f"quantgambit_candles:{tenant_id}:{bot_id}",
    )
    consumer_name = os.getenv("CANDLE_CONSUMER_NAME", "candle_worker_cli")

    log_info(
        "candle_worker_cli_start",
        redis_url=redis_url,
        source_stream=source_stream,
        output_stream=output_stream,
        consumer_group=consumer_group,
        consumer_name=consumer_name,
        tenant_id=tenant_id,
        bot_id=bot_id,
        exchange=exchange,
    )

    redis_client = redis.from_url(redis_url)
    streams = RedisStreamsClient(redis_client)
    timescale = NullTimescaleWriter()

    worker = CandleWorker(
        redis_client=streams,
        timescale=timescale,
        tenant_id=tenant_id,
        bot_id=bot_id,
        exchange=exchange,
        config=CandleWorkerConfig(
            source_stream=source_stream,
            output_stream=output_stream,
            consumer_group=consumer_group,
            consumer_name=consumer_name,
        ),
    )

    try:
        await worker.run()
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        log_info("candle_worker_cli_stopped")
    finally:
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(_main())
