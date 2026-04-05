"""Exchange-authoritative execution reconciliation worker.

Goal: eliminate drift between exchange executions and local trade history/PnL.

For Bybit demo/testnet, CCXT execution endpoints can be incomplete or unsupported.
This worker uses Bybit V5 `GET /v5/execution/list` as the authoritative source,
upserts executions into `execution_ledger`, and emits upgraded `order_events`
rows (reason=exchange_reconcile) so the dashboard matches Bybit.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg
import redis.asyncio as redis

from quantgambit.observability.logger import log_info, log_warning
from quantgambit.storage.secrets import SecretsProvider
from quantgambit.execution.symbols import normalize_exchange_symbol, to_storage_symbol


def _env_str(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val is None:
        return default
    val = str(val).strip()
    return val if val else default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except Exception:
        return default


def _coerce_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def _coerce_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _normalize_symbol(symbol: str) -> str:
    return str(to_storage_symbol(symbol) or "")


def _build_order_event_semantic_key(payload: dict[str, Any], ts: datetime) -> str:
    event_id = str(payload.get("event_id") or "").strip()
    if event_id:
        return f"ev:{event_id}"
    order_id = str(payload.get("order_id") or "").strip()
    client_order_id = str(payload.get("client_order_id") or "").strip()
    if order_id or client_order_id:
        return "|".join(
            [
                "ord",
                order_id,
                client_order_id,
                str(payload.get("status") or "").strip(),
                str(payload.get("event_type") or "").strip(),
                str(payload.get("reason") or "").strip(),
                str(payload.get("filled_size") or "").strip(),
                str(payload.get("remaining_size") or "").strip(),
                str(payload.get("fill_price") or "").strip(),
                str(payload.get("fee_usd") or "").strip(),
            ]
        )
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    return "raw:" + hashlib.sha256(f"{raw}|{ts.isoformat()}".encode("utf-8")).hexdigest()[:24]


def _rows_affected(result: str) -> int:
    try:
        return int(str(result).split()[-1])
    except Exception:
        return 0


def _infer_reconcile_position_effect(agg: dict[str, Any]) -> str:
    if bool(agg.get("closed_pnl_record")):
        return "close"
    client_order_id = str(agg.get("client_order_id") or "").strip().lower()
    if client_order_id.endswith((":sl", ":tp", ":close")):
        return "close"
    raw = agg.get("closed_pnl_raw") or agg.get("raw")
    if isinstance(raw, dict):
        stop_order_type = str(raw.get("stopOrderType") or "").strip().lower()
        if stop_order_type in {"tpslorder", "stoploss", "takeprofit"}:
            return "close"
    return "open"


def _filter_trades_for_known_orders(
    trades: list[dict[str, Any]],
    *,
    known_client_order_ids: set[str],
    known_order_ids: set[str],
) -> list[dict[str, Any]]:
    return [
        trade
        for trade in trades
        if (
            str(trade.get("client_order_id") or "").strip() in known_client_order_ids
            or str(trade.get("order_id") or "").strip() in known_order_ids
        )
    ]


@dataclass(frozen=True)
class ExecutionReconcileConfig:
    interval_sec: float = 30.0
    lookback_sec: float = 3600.0
    overlap_sec: float = 30.0
    limit: int = 200
    max_pages: int = 10
    bybit_category: str = "linear"
    write_order_events: bool = True
    # Default to treating Bybit closedPnl as already net-of-fees for UI parity.
    # Fees are displayed separately; double-subtracting is worse than showing gross.
    closed_pnl_is_net: bool = True


def _bybit_v5_signature(
    api_key: str,
    api_secret: str,
    query_string: str,
    recv_window: str,
    timestamp_ms: str,
) -> str:
    payload = f"{timestamp_ms}{api_key}{recv_window}{query_string}"
    return hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _bybit_v5_get(
    base_url: str,
    api_key: str,
    api_secret: str,
    path: str,
    params: dict[str, Any],
    recv_window_ms: int = 5000,
) -> dict:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    last_payload: dict[str, Any] = {}
    base_recv_window_ms = max(int(recv_window_ms or 5000), 1000)
    for attempt in range(3):
        recv_window = str(base_recv_window_ms if attempt < 2 else min(base_recv_window_ms * 2, 20000))
        timestamp_int = _bybit_server_time_ms(base_url) if attempt > 0 else int(time.time() * 1000)
        timestamp_ms = str(timestamp_int if timestamp_int else int(time.time() * 1000))
        signature = _bybit_v5_signature(api_key, api_secret, query, recv_window, timestamp_ms)
        url = f"{base_url}{path}?{query}"
        headers = {
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": timestamp_ms,
            "X-BAPI-RECV-WINDOW": recv_window,
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
            payload = json.loads(raw.decode("utf-8"))
            last_payload = payload if isinstance(payload, dict) else {}
            if str(last_payload.get("retCode")) != "10002":
                return last_payload
            log_warning(
                "execution_reconcile_bybit_time_drift_retry",
                path=path,
                retCode=str(last_payload.get("retCode")),
                retMsg=str(last_payload.get("retMsg") or ""),
                attempt=attempt + 1,
            )
            time.sleep(0.12)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""
            last_payload = {"retCode": str(exc.code), "retMsg": body[:500]}
            if attempt >= 2:
                return last_payload
            time.sleep(0.12)
        except Exception:
            if attempt >= 2:
                raise
            time.sleep(0.12)
    return last_payload


def _bybit_server_time_ms(base_url: str) -> Optional[int]:
    """Best-effort server clock fetch for signed endpoint timestamp drift mitigation."""
    try:
        req = urllib.request.Request(f"{base_url}/v5/market/time", method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
        payload = json.loads(raw.decode("utf-8"))
        if str(payload.get("retCode")) not in {"0", "None"}:
            return None
        result = payload.get("result") or {}
        time_ms = _coerce_int(result.get("time"))
        if time_ms:
            return time_ms
        time_sec = _coerce_int(result.get("timeSecond"))
        if time_sec:
            return int(time_sec) * 1000
    except Exception:
        return None
    return None


def _fetch_bybit_v5_execs(
    api_key: str,
    api_secret: str,
    symbols: list[str],
    category: str,
    start_ms: int,
    end_ms: int,
    limit: int,
    base_url: str,
    max_pages: int,
) -> list[dict]:
    trades: list[dict] = []
    for symbol in symbols:
        cursor: Optional[str] = None
        for _ in range(max_pages):
            params = {
                "category": category,
                "symbol": symbol,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": limit,
                "cursor": cursor,
            }
            payload = _bybit_v5_get(base_url, api_key, api_secret, "/v5/execution/list", params)
            ret_code = payload.get("retCode")
            if ret_code not in (0, "0"):
                log_warning(
                    "execution_reconcile_bybit_v5_failed",
                    symbol=symbol,
                    retCode=str(ret_code),
                    retMsg=str(payload.get("retMsg") or ""),
                )
                break
            result = payload.get("result") or {}
            items = result.get("list") or []
            for item in items:
                trades.append(
                    {
                        "order_id": item.get("orderId"),
                        "client_order_id": item.get("orderLinkId"),
                        "exec_id": item.get("execId"),
                        "symbol": _normalize_symbol(item.get("symbol") or symbol),
                        "exec_time_ms": _coerce_int(item.get("execTime")),
                        "exec_price": _coerce_float(item.get("execPrice")),
                        "exec_qty": _coerce_float(item.get("execQty")),
                        "exec_fee_usd": _coerce_float(item.get("execFee")),
                        "side": (item.get("side") or "").lower() or None,
                        "exec_pnl": _coerce_float(item.get("execPnl")),
                        "raw": item,
                    }
                )
            cursor = result.get("nextPageCursor")
            if not cursor or not items:
                break
    return trades


def _fetch_bybit_v5_closed_pnl(
    api_key: str,
    api_secret: str,
    symbols: list[str],
    category: str,
    start_ms: int,
    end_ms: int,
    limit: int,
    base_url: str,
    max_pages: int,
) -> dict[str, dict]:
    """Fetch Bybit closed PnL records keyed by order_id.

    Bybit executions may omit/zero `execPnl` depending on account mode.
    Closed PnL is the exchange-authoritative realized PnL for a close.
    """
    by_order: dict[str, dict] = {}
    for symbol in symbols:
        cursor: Optional[str] = None
        for _ in range(max_pages):
            params = {
                "category": category,
                "symbol": symbol,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": limit,
                "cursor": cursor,
            }
            payload = _bybit_v5_get(base_url, api_key, api_secret, "/v5/position/closed-pnl", params)
            ret_code = payload.get("retCode")
            if ret_code not in (0, "0"):
                log_warning(
                    "execution_reconcile_bybit_closed_pnl_failed",
                    symbol=symbol,
                    retCode=str(ret_code),
                    retMsg=str(payload.get("retMsg") or ""),
                )
                break
            result = payload.get("result") or {}
            items = result.get("list") or []
            for item in items:
                order_id = item.get("orderId") or item.get("orderID")
                if not order_id:
                    continue
                oid = str(order_id)
                pnl = _coerce_float(item.get("closedPnl") or item.get("closedPnlUsd") or item.get("closedPnlUSDT"))
                avg_entry = _coerce_float(item.get("avgEntryPrice") or item.get("avgEntryPriceE8"))
                avg_exit = _coerce_float(item.get("avgExitPrice") or item.get("avgExitPriceE8"))
                qty = _coerce_float(item.get("qty") or item.get("closedSize") or item.get("size"))
                updated_ms = _coerce_int(item.get("updatedTime") or item.get("createdTime"))
                rec = {
                    "order_id": oid,
                    "symbol": _normalize_symbol(item.get("symbol") or symbol),
                    "closed_pnl": pnl,
                    "avg_entry_price": avg_entry,
                    "avg_exit_price": avg_exit,
                    "qty": qty,
                    "updated_time_ms": updated_ms,
                    "raw": item,
                }
                existing = by_order.get(oid)
                if existing is None:
                    by_order[oid] = rec
                else:
                    # Keep the most recent record.
                    existing_ts = _coerce_int(existing.get("updated_time_ms")) or 0
                    new_ts = _coerce_int(updated_ms) or 0
                    if new_ts >= existing_ts:
                        by_order[oid] = rec
            cursor = result.get("nextPageCursor")
            if not cursor or not items:
                break
    return by_order


def _aggregate_by_order(trades: list[dict]) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    for t in trades:
        order_id = t.get("order_id")
        if not order_id:
            continue
        entry = grouped.get(str(order_id))
        if entry is None:
            entry = {
                "order_id": str(order_id),
                "client_order_id": t.get("client_order_id"),
                "symbol": t.get("symbol"),
                "side": t.get("side"),
                "raw": t.get("raw"),
                "total_qty": 0.0,
                "total_fee_usd": 0.0,
                "exec_pnl": 0.0,
                "notional": 0.0,
                "first_exec_time_ms": t.get("exec_time_ms"),
                "last_exec_time_ms": t.get("exec_time_ms"),
                "exec_count": 0,
            }
            grouped[str(order_id)] = entry
        qty = t.get("exec_qty") or 0.0
        price = t.get("exec_price") or 0.0
        fee = t.get("exec_fee_usd") or 0.0
        pnl = t.get("exec_pnl") or 0.0
        entry["total_qty"] += qty
        entry["total_fee_usd"] += fee
        entry["exec_pnl"] += pnl
        entry["notional"] += qty * price
        entry["exec_count"] += 1
        ts = t.get("exec_time_ms")
        if ts is not None:
            entry["first_exec_time_ms"] = (
                ts
                if entry["first_exec_time_ms"] is None
                else min(entry["first_exec_time_ms"], ts)
            )
            entry["last_exec_time_ms"] = (
                ts
                if entry["last_exec_time_ms"] is None
                else max(entry["last_exec_time_ms"], ts)
            )
        if not entry.get("client_order_id") and t.get("client_order_id"):
            entry["client_order_id"] = t.get("client_order_id")
        if not entry.get("side") and t.get("side"):
            entry["side"] = t.get("side")
        if not isinstance(entry.get("raw"), dict) and isinstance(t.get("raw"), dict):
            entry["raw"] = t.get("raw")
    for entry in grouped.values():
        qty = entry["total_qty"]
        entry["avg_price"] = (entry["notional"] / qty) if qty else None
    return grouped


class ExecutionReconcileWorker:
    def __init__(
        self,
        *,
        tenant_id: str,
        bot_id: str,
        exchange: str,
        secret_id: str,
        symbols: list[str],
        dsn: str,
        redis_url: str,
        demo: bool,
        testnet: bool,
        config: ExecutionReconcileConfig,
    ):
        self.tenant_id = tenant_id
        self.bot_id = bot_id
        self.exchange = exchange
        self.secret_id = secret_id
        self.symbols = symbols
        self._api_symbols = [
            str(normalize_exchange_symbol(exchange, symbol) or symbol)
            for symbol in symbols
            if str(symbol or "").strip()
        ]
        self.dsn = dsn
        self.redis_url = redis_url
        self.demo = demo
        self.testnet = testnet
        self.config = config

        self._pool: Optional[asyncpg.Pool] = None
        self._redis = None

    async def _load_known_order_keys(self) -> tuple[set[str], set[str]]:
        if not self._pool:
            return set(), set()
        async with self._pool.acquire() as conn:
            intent_rows = await conn.fetch(
                """
                SELECT DISTINCT client_order_id, order_id
                FROM order_intents
                WHERE tenant_id=$1 AND bot_id=$2
                """,
                self.tenant_id,
                self.bot_id,
            )
            state_rows = await conn.fetch(
                """
                SELECT DISTINCT client_order_id, order_id
                FROM order_states
                WHERE tenant_id=$1 AND bot_id=$2
                  AND lower(coalesce(state_source, '')) <> 'exchange_reconcile'
                """,
                self.tenant_id,
                self.bot_id,
            )
            event_rows = await conn.fetch(
                """
                SELECT DISTINCT
                    nullif(trim(coalesce(payload->>'client_order_id', '')), '') AS client_order_id,
                    nullif(trim(coalesce(payload->>'order_id', '')), '') AS order_id
                FROM order_events
                WHERE tenant_id=$1 AND bot_id=$2
                  AND lower(coalesce(payload->>'source', '')) <> 'exchange_reconcile'
                  AND lower(coalesce(payload->>'reason', '')) NOT LIKE 'exchange_reconcile%%'
                """,
                self.tenant_id,
                self.bot_id,
            )
        known_client_order_ids: set[str] = set()
        known_order_ids: set[str] = set()
        for rows in (intent_rows, state_rows, event_rows):
            for row in rows:
                client_order_id = str(row.get("client_order_id") or "").strip()
                order_id = str(row.get("order_id") or "").strip()
                if client_order_id:
                    known_client_order_ids.add(client_order_id)
                if order_id:
                    known_order_ids.add(order_id)
        return known_client_order_ids, known_order_ids

    def _derive_pnl_fields(
        self,
        *,
        closed_pnl: Optional[float],
        total_fee_usd: Optional[float],
    ) -> tuple[Optional[float], Optional[float]]:
        """Return (gross_pnl, net_pnl) from exchange closed pnl + fee semantics."""
        if closed_pnl is None:
            return None, None
        if self.config.closed_pnl_is_net:
            net_pnl = closed_pnl
            gross_pnl = closed_pnl + total_fee_usd if total_fee_usd is not None else closed_pnl
            return gross_pnl, net_pnl
        gross_pnl = closed_pnl
        net_pnl = (closed_pnl - total_fee_usd) if total_fee_usd is not None else closed_pnl
        return gross_pnl, net_pnl

    async def run(self) -> None:
        log_info(
            "execution_reconcile_start",
            tenant_id=self.tenant_id,
            bot_id=self.bot_id,
            exchange=self.exchange,
            symbols=self.symbols,
            interval_sec=self.config.interval_sec,
            demo=self.demo,
            testnet=self.testnet,
        )
        self._pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=4)
        self._redis = redis.from_url(self.redis_url, decode_responses=False)
        await self._ensure_order_execution_summary_schema()
        await self._ensure_execution_ledger_schema()

        while True:
            try:
                await self.reconcile_once()
            except Exception as exc:
                log_warning("execution_reconcile_failed", error=str(exc))
            await asyncio.sleep(max(5.0, float(self.config.interval_sec)))

    async def reconcile_once(self) -> None:
        if self.exchange.lower() != "bybit":
            log_warning("execution_reconcile_unsupported", exchange=self.exchange)
            return

        baseline_key = f"quantgambit:{self.tenant_id}:{self.bot_id}:execution_reconcile:baseline_ms"
        key = f"quantgambit:{self.tenant_id}:{self.bot_id}:execution_reconcile:last_ms"
        raw_baseline = await self._redis.get(baseline_key)
        raw_last = await self._redis.get(key)
        baseline_ms = int(raw_baseline) if raw_baseline else None
        last_ms = int(raw_last) if raw_last else None
        now_ms = int(time.time() * 1000)
        lookback_ms = int(max(30.0, float(self.config.lookback_sec)) * 1000)
        overlap_ms = int(max(0.0, float(self.config.overlap_sec)) * 1000)
        if last_ms is None:
            since_ms = now_ms - lookback_ms
        else:
            since_ms = max(0, last_ms - overlap_ms)
        if baseline_ms is not None:
            # After a reset, we only reconcile executions that occur after the baseline.
            since_ms = max(since_ms, int(baseline_ms))

        base_url = "https://api.bybit.com"
        if self.demo:
            base_url = "https://api-demo.bybit.com"
        elif self.testnet:
            base_url = "https://api-testnet.bybit.com"

        provider = SecretsProvider()
        creds = provider.get_credentials(self.secret_id)
        if creds is None:
            log_warning("execution_reconcile_missing_creds", secret_id=self.secret_id)
            return

        known_client_order_ids, known_order_ids = await self._load_known_order_keys()

        # Pull exchange-truth executions and closed-PnL in the same window.
        fetched_trades = _fetch_bybit_v5_execs(
            api_key=creds.api_key,
            api_secret=creds.secret_key,
            symbols=self._api_symbols,
            category=self.config.bybit_category,
            start_ms=since_ms,
            end_ms=now_ms,
            limit=max(1, int(self.config.limit)),
            base_url=base_url,
            max_pages=max(1, int(self.config.max_pages)),
        )
        trades = _filter_trades_for_known_orders(
            fetched_trades,
            known_client_order_ids=known_client_order_ids,
            known_order_ids=known_order_ids,
        )
        closed_pnl_by_order = _fetch_bybit_v5_closed_pnl(
            api_key=creds.api_key,
            api_secret=creds.secret_key,
            symbols=self._api_symbols,
            category=self.config.bybit_category,
            start_ms=since_ms,
            end_ms=now_ms,
            limit=max(1, int(self.config.limit)),
            base_url=base_url,
            max_pages=max(1, int(self.config.max_pages)),
        )
        if not trades:
            if last_ms is None:
                new_last = now_ms - overlap_ms
                if baseline_ms is not None:
                    new_last = max(int(baseline_ms), int(new_last))
                await self._redis.set(key, str(int(new_last)))
            return

        fetched_max_ts = None
        for t in trades:
            ts = t.get("exec_time_ms")
            if ts is None:
                continue
            fetched_max_ts = ts if fetched_max_ts is None else max(fetched_max_ts, ts)

        ledger_upserted = await self._upsert_execution_ledger_rows(trades)
        aggregates = _aggregate_by_order(trades)
        # Prefer exchange closed PnL (order-level), otherwise fall back to summed exec_pnl.
        for order_id, agg in aggregates.items():
            rec = closed_pnl_by_order.get(order_id)
            if not rec:
                continue
            agg["closed_pnl_record"] = True
            agg["closed_pnl_raw"] = rec.get("raw")
            agg["closed_pnl_updated_time_ms"] = rec.get("updated_time_ms")
            agg["avg_entry_price"] = _coerce_float(rec.get("avg_entry_price"))
            agg["avg_exit_price"] = _coerce_float(rec.get("avg_exit_price"))
            agg["closed_qty"] = _coerce_float(rec.get("qty"))
            if rec.get("closed_pnl") is not None:
                closed_pnl_value = _coerce_float(rec.get("closed_pnl"))
                agg["exec_pnl"] = closed_pnl_value
                agg["closed_pnl"] = closed_pnl_value
                fee = _coerce_float(agg.get("total_fee_usd"))
                gross_pnl, net_pnl = self._derive_pnl_fields(closed_pnl=closed_pnl_value, total_fee_usd=fee)
                agg["gross_pnl"] = gross_pnl
                agg["net_pnl"] = net_pnl
        summary_upserted = await self._upsert_order_execution_summary_rows(list(aggregates.values()))

        inserted_events = 0
        upserted_states = 0
        if self.config.write_order_events and aggregates:
            order_ids = list(aggregates.keys())
            existing = await self._fetch_latest_order_summaries(order_ids)
            for order_id, agg in aggregates.items():
                if not self._should_emit_reconcile_event(agg, existing.get(order_id)):
                    continue
                await self._insert_order_event_reconcile(agg)
                await self._upsert_order_state_reconcile(agg)
                inserted_events += 1
                upserted_states += 1

        if fetched_max_ts is not None:
            await self._redis.set(key, str(int(fetched_max_ts)))

        log_info(
            "execution_reconcile_complete",
            since_ms=since_ms,
            fetched=len(fetched_trades),
            matched_bot_orders=len(trades),
            skipped_unowned=max(0, len(fetched_trades) - len(trades)),
            aggregated=len(aggregates),
            ledger_upserted=ledger_upserted,
            summary_upserted=summary_upserted,
            order_events_inserted=inserted_events,
            order_states_upserted=upserted_states,
        )

    async def _ensure_execution_ledger_schema(self) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_ledger (
                    tenant_id text NOT NULL,
                    bot_id text NOT NULL,
                    exchange text NOT NULL,
                    exec_id text NOT NULL,
                    order_id text,
                    client_order_id text,
                    symbol text NOT NULL,
                    side text,
                    exec_price double precision,
                    exec_qty double precision,
                    exec_value double precision,
                    exec_fee_usd double precision,
                    exec_pnl double precision,
                    exec_time_ms bigint,
                    source text NOT NULL DEFAULT 'execution_reconcile',
                    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
                    ingested_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (tenant_id, bot_id, exchange, exec_id)
                )
                """
            )
            # Older schema variants may not include exec_pnl; add it in-place.
            await conn.execute("ALTER TABLE execution_ledger ADD COLUMN IF NOT EXISTS exec_pnl double precision")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS execution_ledger_order_idx ON execution_ledger(tenant_id, bot_id, exchange, order_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS execution_ledger_time_idx ON execution_ledger(tenant_id, bot_id, exchange, exec_time_ms DESC)"
            )

    async def _ensure_order_execution_summary_schema(self) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS order_execution_summary (
                    tenant_id text NOT NULL,
                    bot_id text NOT NULL,
                    exchange text NOT NULL,
                    order_id text NOT NULL,
                    client_order_id text,
                    symbol text NOT NULL,
                    side text,
                    exec_count integer NOT NULL DEFAULT 0,
                    total_qty double precision,
                    avg_price double precision,
                    total_fee_usd double precision,
                    exec_pnl double precision,
                    first_exec_time_ms bigint,
                    last_exec_time_ms bigint,
                    source text NOT NULL DEFAULT 'execution_reconcile',
                    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (tenant_id, bot_id, exchange, order_id)
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS order_execution_summary_time_idx ON order_execution_summary(tenant_id, bot_id, exchange, last_exec_time_ms DESC)"
            )

    async def _upsert_execution_ledger_rows(self, trades: list[dict]) -> int:
        if not trades or not self._pool:
            return 0
        rows = []
        for t in trades:
            exec_id = t.get("exec_id")
            order_id = t.get("order_id")
            symbol = _normalize_symbol(str(t.get("symbol") or ""))
            if not exec_id or not symbol:
                continue
            price = _coerce_float(t.get("exec_price"))
            qty = _coerce_float(t.get("exec_qty"))
            fee = _coerce_float(t.get("exec_fee_usd"))
            pnl = _coerce_float(t.get("exec_pnl"))
            ts_ms = _coerce_int(t.get("exec_time_ms"))
            value = None
            if price is not None and qty is not None:
                value = price * qty
            rows.append(
                (
                    self.tenant_id,
                    self.bot_id,
                    self.exchange,
                    str(exec_id),
                    str(order_id) if order_id else None,
                    str(t.get("client_order_id")) if t.get("client_order_id") else None,
                    symbol,
                    t.get("side"),
                    price,
                    qty,
                    value,
                    fee,
                    pnl,
                    ts_ms,
                    "execution_reconcile",
                    json.dumps(t.get("raw") or {}, separators=(",", ":"), sort_keys=True),
                )
            )
        if not rows:
            return 0
        upsert_sql = """
                INSERT INTO execution_ledger (
                    tenant_id, bot_id, exchange, exec_id, order_id, client_order_id,
                    symbol, side, exec_price, exec_qty, exec_value, exec_fee_usd,
                    exec_pnl, exec_time_ms, source, raw
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb)
                ON CONFLICT (tenant_id, bot_id, exchange, exec_id)
                DO UPDATE SET
                    order_id = COALESCE(EXCLUDED.order_id, execution_ledger.order_id),
                    client_order_id = COALESCE(EXCLUDED.client_order_id, execution_ledger.client_order_id),
                    symbol = COALESCE(EXCLUDED.symbol, execution_ledger.symbol),
                    side = COALESCE(EXCLUDED.side, execution_ledger.side),
                    exec_price = COALESCE(EXCLUDED.exec_price, execution_ledger.exec_price),
                    exec_qty = COALESCE(EXCLUDED.exec_qty, execution_ledger.exec_qty),
                    exec_value = COALESCE(EXCLUDED.exec_value, execution_ledger.exec_value),
                    exec_fee_usd = COALESCE(EXCLUDED.exec_fee_usd, execution_ledger.exec_fee_usd),
                    exec_pnl = COALESCE(EXCLUDED.exec_pnl, execution_ledger.exec_pnl),
                    exec_time_ms = COALESCE(EXCLUDED.exec_time_ms, execution_ledger.exec_time_ms),
                    source = EXCLUDED.source,
                    raw = EXCLUDED.raw,
                    updated_at = now()
                """
        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(upsert_sql, rows)
        except asyncpg.UndefinedColumnError:
            log_warning("execution_reconcile_ledger_schema_retry", reason="undefined_column_exec_pnl")
            await self._ensure_execution_ledger_schema()
            async with self._pool.acquire() as conn:
                await conn.executemany(upsert_sql, rows)
        return len(rows)

    async def _upsert_order_execution_summary_rows(self, summaries: list[dict]) -> int:
        if not summaries or not self._pool:
            return 0
        rows = []
        for s in summaries:
            if not s.get("order_id") or not s.get("symbol"):
                continue
            rows.append(
                (
                    self.tenant_id,
                    self.bot_id,
                    self.exchange,
                    str(s.get("order_id")),
                    str(s.get("client_order_id")) if s.get("client_order_id") else None,
                    _normalize_symbol(str(s.get("symbol"))),
                    (s.get("side") or "").lower() or None,
                    int(s.get("exec_count") or 0),
                    _coerce_float(s.get("total_qty")),
                    _coerce_float(s.get("avg_price")),
                    _coerce_float(s.get("total_fee_usd")),
                    _coerce_float(s.get("exec_pnl")),
                    _coerce_int(s.get("first_exec_time_ms")),
                    _coerce_int(s.get("last_exec_time_ms")),
                    "execution_reconcile",
                    json.dumps(s, separators=(",", ":"), sort_keys=True),
                )
            )
        if not rows:
            return 0
        upsert_sql = """
                INSERT INTO order_execution_summary (
                    tenant_id, bot_id, exchange, order_id, client_order_id, symbol, side,
                    exec_count, total_qty, avg_price, total_fee_usd, exec_pnl,
                    first_exec_time_ms, last_exec_time_ms, source, raw
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb)
                ON CONFLICT (tenant_id, bot_id, exchange, order_id)
                DO UPDATE SET
                    client_order_id = COALESCE(EXCLUDED.client_order_id, order_execution_summary.client_order_id),
                    symbol = COALESCE(EXCLUDED.symbol, order_execution_summary.symbol),
                    side = COALESCE(EXCLUDED.side, order_execution_summary.side),
                    exec_count = GREATEST(order_execution_summary.exec_count, EXCLUDED.exec_count),
                    total_qty = COALESCE(EXCLUDED.total_qty, order_execution_summary.total_qty),
                    avg_price = COALESCE(EXCLUDED.avg_price, order_execution_summary.avg_price),
                    total_fee_usd = COALESCE(EXCLUDED.total_fee_usd, order_execution_summary.total_fee_usd),
                    exec_pnl = COALESCE(EXCLUDED.exec_pnl, order_execution_summary.exec_pnl),
                    first_exec_time_ms = COALESCE(EXCLUDED.first_exec_time_ms, order_execution_summary.first_exec_time_ms),
                    last_exec_time_ms = COALESCE(EXCLUDED.last_exec_time_ms, order_execution_summary.last_exec_time_ms),
                    source = EXCLUDED.source,
                    raw = EXCLUDED.raw,
                    updated_at = now()
                """
        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(upsert_sql, rows)
        except asyncpg.UndefinedColumnError:
            log_warning("execution_reconcile_summary_schema_retry", reason="undefined_column_exec_pnl")
            await self._ensure_order_execution_summary_schema()
            async with self._pool.acquire() as conn:
                await conn.executemany(upsert_sql, rows)
        return len(rows)

    async def _fetch_latest_order_summaries(self, order_ids: list[str]) -> dict[str, dict]:
        if not order_ids or not self._pool:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT ON (payload->>'order_id') "
                "(payload->>'order_id') AS order_id, "
                "(payload->>'filled_size') AS filled_size, "
                "(payload->>'fill_price') AS fill_price, "
                "(payload->>'fee_usd') AS fee_usd, "
                "(payload->>'total_fees_usd') AS total_fees_usd, "
                "(payload->>'gross_pnl') AS gross_pnl, "
                "(payload->>'net_pnl') AS net_pnl, "
                "(payload->>'last_exec_time_ms') AS last_exec_time_ms, "
                "(payload->>'reconciled_at_ms') AS reconciled_at_ms, "
                "(payload->>'reason') AS reason, "
                "(payload->>'symbol') AS symbol "
                "FROM order_events "
                "WHERE tenant_id=$1 AND bot_id=$2 "
                "AND (payload->>'order_id') = ANY($3::text[]) "
                "ORDER BY (payload->>'order_id'), ts DESC",
                self.tenant_id,
                self.bot_id,
                order_ids,
            )
        out: dict[str, dict] = {}
        for row in rows:
            oid = row.get("order_id")
            if not oid:
                continue
            out[str(oid)] = {
                "filled_size": _coerce_float(row.get("filled_size")),
                "fill_price": _coerce_float(row.get("fill_price")),
                "fee_usd": _coerce_float(row.get("fee_usd")),
                "total_fees_usd": _coerce_float(row.get("total_fees_usd")),
                "gross_pnl": _coerce_float(row.get("gross_pnl")),
                "net_pnl": _coerce_float(row.get("net_pnl")),
                "last_exec_time_ms": _coerce_int(row.get("last_exec_time_ms")),
                "reconciled_at_ms": _coerce_int(row.get("reconciled_at_ms")),
                "reason": row.get("reason"),
                "symbol": _normalize_symbol(row.get("symbol") or ""),
            }
        return out

    def _should_emit_reconcile_event(self, aggregate: dict, existing: Optional[dict]) -> bool:
        if not existing:
            return True
        incoming_symbol = _normalize_symbol(aggregate.get("symbol") or "")
        existing_symbol = _normalize_symbol(existing.get("symbol") or "")
        if incoming_symbol and existing_symbol and incoming_symbol != existing_symbol:
            return True
        existing_reason = (existing.get("reason") or "").lower()
        # Force a one-time upgrade when we add new fields to the reconcile payload,
        # so the dashboard stops showing placeholder times/values.
        if existing_reason == "exchange_reconcile":
            if existing.get("reconciled_at_ms") is None:
                return True
            if existing.get("last_exec_time_ms") is None and aggregate.get("last_exec_time_ms") is not None:
                return True
        incoming_qty = _coerce_float(aggregate.get("total_qty")) or 0.0
        incoming_price = _coerce_float(aggregate.get("avg_price")) or 0.0
        incoming_fee = _coerce_float(aggregate.get("total_fee_usd")) or 0.0
        incoming_gross = _coerce_float(aggregate.get("gross_pnl"))
        if incoming_gross is None:
            incoming_gross = _coerce_float(aggregate.get("exec_pnl"))
        incoming_net = _coerce_float(aggregate.get("net_pnl"))
        existing_qty = _coerce_float(existing.get("filled_size")) or 0.0
        existing_price = _coerce_float(existing.get("fill_price")) or 0.0
        existing_fee = _coerce_float(existing.get("total_fees_usd"))
        if existing_fee is None:
            existing_fee = _coerce_float(existing.get("fee_usd")) or 0.0
        existing_gross = _coerce_float(existing.get("gross_pnl"))
        existing_net = _coerce_float(existing.get("net_pnl"))

        qty_close = abs(incoming_qty - existing_qty) <= 1e-8
        price_close = abs(incoming_price - existing_price) <= max(1e-8, existing_price * 1e-8)
        fee_close = abs(incoming_fee - existing_fee) <= 1e-8
        gross_close = True
        if incoming_gross is not None and existing_gross is not None:
            gross_close = abs(incoming_gross - existing_gross) <= 1e-8
        net_close = True
        if incoming_net is not None and existing_net is not None:
            net_close = abs(incoming_net - existing_net) <= 1e-8

        if existing_reason in {"exchange_reconcile"} and qty_close and price_close and fee_close and gross_close and net_close:
            return False
        return True

    def _build_reconcile_payload(self, agg: dict) -> tuple[datetime, dict[str, Any]]:
        # Use exchange execution time for ordering/display correctness.
        # We delete old reconcile rows for this order_id, so "latest wins"
        # selection does not require wallclock ordering hacks.
        last_ms = _coerce_int(agg.get("last_exec_time_ms"))
        ts = datetime.fromtimestamp((last_ms or int(time.time() * 1000)) / 1000.0, tz=timezone.utc)
        side = (agg.get("side") or "").lower()
        qty = _coerce_float(agg.get("total_qty"))
        avg_price = _coerce_float(agg.get("avg_price"))
        fee = _coerce_float(agg.get("total_fee_usd"))
        position_effect = _infer_reconcile_position_effect(agg)
        is_close = position_effect == "close"
        gross = _coerce_float(agg.get("gross_pnl"))
        if gross is None:
            closed_pnl = _coerce_float(agg.get("exec_pnl"))
            if is_close:
                derived_gross, derived_net = self._derive_pnl_fields(closed_pnl=closed_pnl, total_fee_usd=fee)
                gross = derived_gross
                net = derived_net
            else:
                net = None
        else:
            net = _coerce_float(agg.get("net_pnl"))
        if net is None:
            if is_close and gross is not None and fee is not None:
                net = gross if self.config.closed_pnl_is_net else (gross - fee)
            else:
                net = None
        avg_entry_price = _coerce_float(agg.get("avg_entry_price"))
        avg_exit_price = _coerce_float(agg.get("avg_exit_price"))
        closed_qty = _coerce_float(agg.get("closed_qty"))
        reconciled_at_ms = int(time.time() * 1000)
        reason = "exchange_reconcile_close" if is_close else "exchange_reconcile_open"
        event_type = "exchange_reconcile_close" if is_close else "exchange_reconcile_open"
        payload: dict[str, Any] = {
            "order_id": agg.get("order_id"),
            "client_order_id": agg.get("client_order_id"),
            "symbol": agg.get("symbol"),
            "status": "filled",
            "reason": reason,
            "source": "exchange_reconcile",
            "event_type": event_type,
            "side": "buy" if side == "buy" else ("sell" if side == "sell" else side),
            "filled_size": qty,
            "size": qty,
            "fill_price": avg_price,
            "fee_usd": fee,
            "total_fees_usd": fee,
            "entry_price": avg_entry_price,
            "exit_price": avg_exit_price,
            "closed_qty": closed_qty,
            "exec_count": int(agg.get("exec_count") or 0),
            "first_exec_time_ms": _coerce_int(agg.get("first_exec_time_ms")),
            "last_exec_time_ms": last_ms,
            "reconciled_at_ms": reconciled_at_ms,
            "exchange_reconciled": True,
        }
        if is_close:
            payload["gross_pnl"] = gross
            payload["net_pnl"] = net
            payload["realized_pnl"] = net
            payload["pnl_source"] = "bybit_closed_pnl"
            payload["closed_pnl_is_net"] = bool(self.config.closed_pnl_is_net)
            payload["position_effect"] = "close"
        else:
            payload["position_effect"] = "open"
        return ts, payload

    async def _insert_order_event_reconcile(self, agg: dict) -> None:
        if not self._pool:
            return
        ts, payload = self._build_reconcile_payload(agg)
        semantic_key = _build_order_event_semantic_key(payload, ts)

        async with self._pool.acquire() as conn:
            # Remove old reconcile rows for this order_id to avoid duplicates fighting
            # in trade-history selection.
            await conn.execute(
                """
                DELETE FROM order_events
                WHERE tenant_id=$1 AND bot_id=$2
                AND (payload->>'order_id')=$3
                AND (payload->>'reason') IN ('exchange_reconcile', 'exchange_reconcile_open', 'exchange_reconcile_close')
                AND COALESCE(payload->>'symbol','')=$4
                """,
                self.tenant_id,
                self.bot_id,
                str(agg.get("order_id") or ""),
                str(agg.get("symbol") or ""),
            )
            await conn.execute(
                """
                WITH incoming AS (
                    SELECT $6::jsonb AS payload
                )
                INSERT INTO order_events (
                    tenant_id, bot_id, symbol, exchange, ts,
                    order_id, client_order_id, event_type, status, reason,
                    fill_price, filled_size, fee_usd,
                    payload, semantic_key
                )
                SELECT
                    $1, $2, $3, $4, $5,
                    nullif(trim(coalesce(incoming.payload->>'order_id', '')), ''),
                    nullif(trim(coalesce(incoming.payload->>'client_order_id', '')), ''),
                    nullif(trim(coalesce(incoming.payload->>'event_type', '')), ''),
                    nullif(trim(coalesce(incoming.payload->>'status', '')), ''),
                    nullif(trim(coalesce(incoming.payload->>'reason', '')), ''),
                    NULLIF(incoming.payload->>'fill_price', '')::double precision,
                    NULLIF(incoming.payload->>'filled_size', '')::double precision,
                    NULLIF(incoming.payload->>'fee_usd', '')::double precision,
                    incoming.payload, $7
                FROM incoming
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM order_events oe
                    WHERE oe.tenant_id = $1
                      AND oe.bot_id = $2
                      AND (
                          oe.semantic_key = $7
                          OR (
                              oe.symbol IS NOT DISTINCT FROM $3
                              AND oe.exchange = $4
                              AND oe.ts = $5
                              AND oe.payload = incoming.payload
                          )
                      )
                )
                """,
                self.tenant_id,
                self.bot_id,
                _normalize_symbol(str(agg.get("symbol") or "")),
                self.exchange,
                ts,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                semantic_key,
            )

    async def _upsert_order_state_reconcile(self, agg: dict) -> None:
        if not self._pool:
            return
        last_ms = _coerce_int(agg.get("last_exec_time_ms"))
        first_ms = _coerce_int(agg.get("first_exec_time_ms"))
        qty = _coerce_float(agg.get("total_qty"))
        size = qty if qty is not None else 0.0
        updated_at = datetime.fromtimestamp((last_ms or int(time.time() * 1000)) / 1000.0, tz=timezone.utc)
        submitted_at = (
            datetime.fromtimestamp(first_ms / 1000.0, tz=timezone.utc) if first_ms is not None else None
        )
        filled_at = updated_at
        state_source = "exchange_reconcile"
        position_effect = _infer_reconcile_position_effect(agg)
        reason = "exchange_reconcile_close" if position_effect == "close" else "exchange_reconcile_open"
        update_query = (
            "UPDATE order_states SET "
            "exchange=$4, symbol=$5, side=$6, size=$7, status=$8, "
            "order_id=COALESCE($9, order_id), client_order_id=COALESCE($10, client_order_id), "
            "reason=$11, fill_price=$12, fee_usd=$13, filled_size=$14, remaining_size=$15, "
            "state_source=$16, raw_exchange_status=$17, "
            "submitted_at=COALESCE($18, submitted_at), accepted_at=COALESCE($19, accepted_at), "
            "open_at=COALESCE($20, open_at), filled_at=COALESCE($21, filled_at), "
            "updated_at=$22 "
            "WHERE tenant_id=$1 AND bot_id=$2 AND {predicate}"
        )
        async with self._pool.acquire() as conn:
            updated = "UPDATE 0"
            client_order_id = str(agg.get("client_order_id") or "").strip() or None
            order_id = str(agg.get("order_id") or "").strip() or None
            if client_order_id:
                updated = await conn.execute(
                    update_query.format(predicate="client_order_id=$3"),
                    self.tenant_id,
                    self.bot_id,
                    client_order_id,
                    self.exchange,
                    _normalize_symbol(str(agg.get("symbol") or "")) or None,
                    (agg.get("side") or "").lower() or None,
                    size,
                    "filled",
                    order_id,
                    client_order_id,
                    reason,
                    _coerce_float(agg.get("avg_price")),
                    _coerce_float(agg.get("total_fee_usd")),
                    qty,
                    0.0,
                    state_source,
                    "filled",
                    submitted_at,
                    submitted_at,
                    submitted_at,
                    filled_at,
                    updated_at,
                )
            if _rows_affected(updated) <= 0 and order_id:
                updated = await conn.execute(
                    update_query.format(predicate="order_id=$3"),
                    self.tenant_id,
                    self.bot_id,
                    order_id,
                    self.exchange,
                    _normalize_symbol(str(agg.get("symbol") or "")) or None,
                    (agg.get("side") or "").lower() or None,
                    size,
                    "filled",
                    order_id,
                    client_order_id,
                    reason,
                    _coerce_float(agg.get("avg_price")),
                    _coerce_float(agg.get("total_fee_usd")),
                    qty,
                    0.0,
                    state_source,
                    "filled",
                    submitted_at,
                    submitted_at,
                    submitted_at,
                    filled_at,
                    updated_at,
                )
            if _rows_affected(updated) > 0:
                return
            await conn.execute(
                """
                INSERT INTO order_states (
                    tenant_id, bot_id, exchange, symbol, side, size, status, order_id, client_order_id,
                    reason, fill_price, fee_usd, filled_size, remaining_size, state_source, raw_exchange_status,
                    submitted_at, accepted_at, open_at, filled_at, updated_at
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)
                """,
                self.tenant_id,
                self.bot_id,
                self.exchange,
                _normalize_symbol(str(agg.get("symbol") or "")) or None,
                (agg.get("side") or "").lower() or None,
                size,
                "filled",
                order_id,
                client_order_id,
                reason,
                _coerce_float(agg.get("avg_price")),
                _coerce_float(agg.get("total_fee_usd")),
                qty,
                0.0,
                state_source,
                "filled",
                submitted_at,
                submitted_at,
                submitted_at,
                filled_at,
                updated_at,
            )


async def main() -> int:
    tenant_id = _env_str("TENANT_ID", _env_str("DEFAULT_TENANT_ID", ""))
    bot_id = _env_str("BOT_ID", _env_str("DEFAULT_BOT_ID", ""))
    exchange = _env_str("ACTIVE_EXCHANGE", "bybit")
    secret_id = _env_str("EXCHANGE_SECRET_ID", "")
    dsn = _env_str("BOT_TIMESCALE_URL", "")
    redis_url = _env_str("REDIS_URL", "redis://localhost:6379")
    symbols = [s.strip() for s in _env_str("ORDERBOOK_SYMBOLS", "").split(",") if s.strip()]

    demo = _env_bool("BYBIT_DEMO", _env_bool("ORDER_UPDATES_DEMO", False))
    testnet = _env_bool("BYBIT_TESTNET", _env_bool("ORDERBOOK_TESTNET", False))

    enabled = _env_bool("EXECUTION_RECONCILE_ENABLED", True)
    if not enabled:
        log_info("execution_reconcile_disabled", reason="EXECUTION_RECONCILE_ENABLED=false")
        return 0

    if not tenant_id or not bot_id or not dsn or not secret_id or not symbols:
        log_warning(
            "execution_reconcile_missing_config",
            tenant_id=tenant_id or None,
            bot_id=bot_id or None,
            has_dsn=bool(dsn),
            has_secret_id=bool(secret_id),
            symbols=symbols,
        )
        return 2

    config = ExecutionReconcileConfig(
        interval_sec=max(5.0, _env_float("EXECUTION_RECONCILE_INTERVAL_SEC", 30.0)),
        lookback_sec=max(30.0, _env_float("EXECUTION_RECONCILE_LOOKBACK_SEC", 3600.0)),
        overlap_sec=max(0.0, _env_float("EXECUTION_RECONCILE_OVERLAP_SEC", 30.0)),
        limit=max(50, _env_int("EXECUTION_RECONCILE_LIMIT", 200)),
        max_pages=max(1, _env_int("EXECUTION_RECONCILE_MAX_PAGES", 10)),
        bybit_category=_env_str("BYBIT_V5_CATEGORY", "linear"),
        write_order_events=_env_bool("EXECUTION_RECONCILE_WRITE_ORDER_EVENTS", True),
        closed_pnl_is_net=_env_bool("EXECUTION_RECONCILE_CLOSED_PNL_IS_NET", True),
    )

    worker = ExecutionReconcileWorker(
        tenant_id=tenant_id,
        bot_id=bot_id,
        exchange=exchange,
        secret_id=secret_id,
        symbols=symbols,
        dsn=dsn,
        redis_url=redis_url,
        demo=demo,
        testnet=testnet,
        config=config,
    )
    await worker.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
