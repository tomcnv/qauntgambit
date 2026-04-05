#!/usr/bin/env python3
"""Soak harness for ResilientMarketDataProvider failure + guardrail throttling."""

from __future__ import annotations

import argparse
import asyncio
import time

from quantgambit.runtime.entrypoint import ResilientMarketDataProvider


class DummyProvider:
    def __init__(self, *, name: str, fail: bool = True):
        self.name = name
        self.fail = fail

    async def next_tick(self):
        if self.fail:
            raise RuntimeError(f"{self.name} no data")
        return {"symbol": "BTCUSDT", "timestamp": time.time(), "bid": 1, "ask": 2, "last": 1.5}


class DummyTelemetry:
    def __init__(self):
        self.guardrails = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append(payload)


async def _run(args: argparse.Namespace) -> int:
    primary = DummyProvider(name="ws", fail=True)
    fallback = DummyProvider(name="ccxt", fail=args.fallback_success is False)
    provider = ResilientMarketDataProvider(
        providers=[primary, fallback],
        provider_names=["ws", "ccxt"],
        switch_threshold=args.switch_threshold,
        idle_backoff_sec=0.0,
        guardrail_cooldown_sec=args.guardrail_cooldown_sec,
    )
    telemetry = DummyTelemetry()
    provider.set_telemetry(telemetry, object())

    for _ in range(args.iterations):
        await provider.next_tick()
        await asyncio.sleep(args.delay_sec)

    switch_events = [event for event in telemetry.guardrails if event.get("type") == "market_data_provider_switch"]
    failure_events = [event for event in telemetry.guardrails if event.get("type") == "market_data_provider_failure"]
    print("market_data_resilience_soak_summary")
    print(f"  iterations: {args.iterations}")
    print(f"  switch_events: {len(switch_events)}")
    print(f"  failure_events: {len(failure_events)}")
    if failure_events:
        print(f"  last_failure_reason: {failure_events[-1].get('reason')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ResilientMarketDataProvider soak harness.")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--delay-sec", type=float, default=0.0)
    parser.add_argument("--switch-threshold", type=int, default=2)
    parser.add_argument("--guardrail-cooldown-sec", type=float, default=5.0)
    parser.add_argument("--fallback-success", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
