"""Trim WS capture logs into fixture JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract fixtures from WS capture logs.")
    parser.add_argument("--input", required=True, help="Path to JSONL capture file.")
    parser.add_argument("--output-dir", default="quantgambit/tests/fixtures/order_updates")
    parser.add_argument("--exchange", choices=["binance", "okx", "bybit"])
    parser.add_argument("--event", help="Optional event name filter (e.g., ORDER_TRADE_UPDATE).")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--prefix", default="fixture")
    return parser.parse_args()


def _matches(entry: dict, exchange: str | None, event: str | None) -> bool:
    if exchange and entry.get("exchange") != exchange:
        return False
    raw = entry.get("raw") or {}
    if event:
        event_value = raw.get("e") or raw.get("event") or raw.get("topic")
        if event_value != event:
            return False
    return True


def main() -> None:
    args = _parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for line in input_path.read_text().splitlines():
        if written >= args.limit:
            break
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not _matches(entry, args.exchange, args.event):
            continue
        raw = entry.get("raw")
        if not raw:
            continue
        output_path = output_dir / f"{args.prefix}_{written + 1}.json"
        output_path.write_text(json.dumps(raw, indent=2, sort_keys=True))
        written += 1
    print(f"fixtures_written={written}")


if __name__ == "__main__":
    main()
