"""Runtime entrypoint for wiring deeptrader queues."""

from __future__ import annotations

import asyncio

from quantgambit.runtime.app import Runtime, RuntimeConfig
from quantgambit.market.deeptrader_event_bridge import DeepTraderEventBridge
from quantgambit.portfolio.state_manager import InMemoryStateManager


async def run_with_deeptrader_queue(redis, timescale_pool, queue, execution_adapter):
    state = InMemoryStateManager()
    config = RuntimeConfig(tenant_id="tenant", bot_id="bot", exchange="okx", trading_mode="live")
    runtime = Runtime(
        config=config,
        redis=redis,
        timescale_pool=timescale_pool,
        state_manager=state,
        market_data_queue=queue,
        execution_adapter=execution_adapter,
    )
    await runtime.start()


async def run_with_event_bus(redis, timescale_pool, event_bus, execution_adapter):
    queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
    DeepTraderEventBridge(event_bus, queue).attach()
    await run_with_deeptrader_queue(redis, timescale_pool, queue, execution_adapter)


if __name__ == "__main__":
    # Placeholder: integrate with actual process launcher.
    asyncio.run(run_with_deeptrader_queue(redis=None, timescale_pool=None, queue=asyncio.Queue(), execution_adapter=None))
