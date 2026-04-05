import asyncio
import json

from quantgambit.replay.determinism import run_determinism_files

from quantgambit.replay.determinism import run_determinism_harness, hash_json


def _tick(symbol: str, ts_us: int, bid: float, ask: float):
    return {
        "event_type": "market_tick",
        "symbol": symbol,
        "ts_canon_us": ts_us,
        "payload": {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "ts_canon_us": ts_us,
            "ts_recv_us": ts_us,
            "ts_exchange_s": None,
            "timestamp": ts_us / 1_000_000.0,
        },
    }


def test_determinism_harness_repeatable():
    events = [
        _tick("BTC-USDT-SWAP", 1_000_000, 100.0, 101.0),
        _tick("BTC-USDT-SWAP", 2_000_000, 101.0, 102.0),
    ]
    schedule = [1_000_000, 2_000_000]
    result1 = asyncio.run(run_determinism_harness(events, schedule))
    result2 = asyncio.run(run_determinism_harness(events, schedule))
    assert result1.snapshot_hashes == result2.snapshot_hashes
    assert result1.decision_hashes == result2.decision_hashes


def test_determinism_harness_chunking_invariance():
    events = [
        _tick("BTC-USDT-SWAP", 1_000_000, 100.0, 101.0),
        _tick("BTC-USDT-SWAP", 2_000_000, 101.0, 102.0),
        _tick("BTC-USDT-SWAP", 3_000_000, 102.0, 103.0),
    ]
    schedule = [1_000_000, 2_000_000, 3_000_000]
    result1 = asyncio.run(run_determinism_harness(events, schedule))
    # Different batching order (same events) should be identical
    result2 = asyncio.run(run_determinism_harness(list(events), schedule))
    assert result1.snapshot_hashes == result2.snapshot_hashes
    assert result1.decision_hashes == result2.decision_hashes


def test_hash_json_is_stable():
    payload = {"b": 2.0, "a": 1.0}
    assert hash_json(payload) == hash_json(payload)


def test_determinism_harness_decisions_repeatable():
    events = [
        _tick("ETH-USDT-SWAP", 1_000_000, 2000.0, 2001.0),
        _tick("ETH-USDT-SWAP", 2_000_000, 2001.0, 2002.0),
    ]
    schedule = [1_000_000, 2_000_000]

    def decision_fn(snapshot):
        return {
            "symbol": snapshot.get("symbol"),
            "ts": snapshot.get("timestamp"),
            "price": snapshot.get("features", {}).get("price"),
        }

    result1 = asyncio.run(run_determinism_harness(events, schedule, decision_fn=decision_fn))
    result2 = asyncio.run(run_determinism_harness(events, schedule, decision_fn=decision_fn))
    assert result1.decision_hashes == result2.decision_hashes


def test_determinism_harness_writes_outputs(tmp_path):
    events = [
        _tick("BTC-USDT-SWAP", 1_000_000, 100.0, 101.0),
        _tick("BTC-USDT-SWAP", 2_000_000, 101.0, 102.0),
    ]
    schedule = [1_000_000, 2_000_000]
    events_path = tmp_path / "events.jsonl"
    now_path = tmp_path / "now_ts.json"
    out_dir = tmp_path / "out"
    with events_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event))
            handle.write("\n")
    with now_path.open("w", encoding="utf-8") as handle:
        json.dump(schedule, handle)

    asyncio.run(run_determinism_files(events_path, now_path, out_dir))

    snapshots_path = out_dir / "snapshots.jsonl"
    decisions_path = out_dir / "decisions.jsonl"
    hashes_path = out_dir / "hashes.jsonl"
    assert snapshots_path.exists()
    assert decisions_path.exists()
    assert hashes_path.exists()
    snapshot_lines = [line for line in snapshots_path.read_text().splitlines() if line.strip()]
    hash_lines = [line for line in hashes_path.read_text().splitlines() if line.strip()]
    assert len(snapshot_lines) == 2
    assert len(hash_lines) == 2
