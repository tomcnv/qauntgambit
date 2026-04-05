"""Postgres persistence for command audit and event logs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import asyncpg


@dataclass(frozen=True)
class CommandAuditRecord:
    command_id: str
    type: str
    scope: Dict[str, Any]
    requested_by: str
    requested_at: str
    status: str
    executed_at: Optional[str] = None
    reason: Optional[str] = None
    result_message: Optional[str] = None


class PostgresAuditStore:
    """Audit writer for commands and optional event logs."""

    def __init__(self, pool):
        self.pool = pool

    async def write_command(self, record: CommandAuditRecord) -> None:
        query = (
            "INSERT INTO command_audit "
            "(command_id, type, scope, reason, requested_by, requested_at, status, executed_at, result_message) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                record.command_id,
                record.type,
                record.scope,
                record.reason,
                record.requested_by,
                record.requested_at,
                record.status,
                record.executed_at,
                record.result_message,
            )


@dataclass(frozen=True)
class OrderStatusRecord:
    tenant_id: str
    bot_id: str
    exchange: Optional[str]
    symbol: str
    side: str
    size: float
    status: str
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    reason: Optional[str] = None
    fill_price: Optional[float] = None
    fee_usd: Optional[float] = None
    filled_size: Optional[float] = None
    remaining_size: Optional[float] = None
    state_source: Optional[str] = None
    raw_exchange_status: Optional[str] = None
    submitted_at: Optional[str] = None
    accepted_at: Optional[str] = None
    open_at: Optional[str] = None
    filled_at: Optional[str] = None
    updated_at: Optional[str] = None
    slippage_bps: Optional[float] = None


@dataclass(frozen=True)
class OrderEventRecord:
    tenant_id: str
    bot_id: str
    exchange: Optional[str]
    symbol: str
    side: str
    size: float
    status: str
    event_type: Optional[str] = None
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    reason: Optional[str] = None
    fill_price: Optional[float] = None
    fee_usd: Optional[float] = None
    filled_size: Optional[float] = None
    remaining_size: Optional[float] = None
    state_source: Optional[str] = None
    raw_exchange_status: Optional[str] = None
    created_at: Optional[str] = None
    slippage_bps: Optional[float] = None


@dataclass(frozen=True)
class OrderIntentRecord:
    intent_id: str
    tenant_id: str
    bot_id: str
    decision_id: Optional[str]
    client_order_id: str
    symbol: str
    side: str
    size: float
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    strategy_id: Optional[str]
    profile_id: Optional[str]
    status: str
    order_id: Optional[str]
    last_error: Optional[str]
    created_at: str
    submitted_at: Optional[str]
    snapshot_metrics: Optional[dict] = None  # Market conditions at entry time (JSONB)


@dataclass(frozen=True)
class OrderErrorRecord:
    error_id: str
    tenant_id: str
    bot_id: str
    exchange: Optional[str]
    symbol: Optional[str]
    order_id: Optional[str]
    client_order_id: Optional[str]
    stage: str
    error_code: Optional[str]
    error_message: Optional[str]
    payload: Optional[Dict[str, Any]]
    created_at: str


@dataclass(frozen=True)
class TradeCostRecord:
    trade_id: str
    symbol: str
    profile_id: Optional[str]
    execution_price: float
    decision_mid_price: float
    slippage_bps: float
    fees: float
    funding_cost: float
    total_cost: float
    order_size: Optional[float]
    side: Optional[str]
    timestamp: Optional[str] = None
    entry_fee_usd: Optional[float] = None
    exit_fee_usd: Optional[float] = None
    entry_fee_bps: Optional[float] = None
    exit_fee_bps: Optional[float] = None
    entry_slippage_bps: Optional[float] = None
    exit_slippage_bps: Optional[float] = None
    spread_cost_bps: Optional[float] = None
    adverse_selection_bps: Optional[float] = None
    total_cost_bps: Optional[float] = None


class PostgresOrderStore:
    """Persist order lifecycle state and events."""

    def __init__(self, pool):
        self.pool = pool

    async def write_order_status(self, record: OrderStatusRecord) -> None:
        if not (record.order_id or record.client_order_id):
            return
        query = (
            "INSERT INTO order_states "
            "(tenant_id, bot_id, exchange, symbol, side, size, status, order_id, client_order_id, "
            "reason, fill_price, fee_usd, filled_size, remaining_size, state_source, raw_exchange_status, "
            "submitted_at, accepted_at, open_at, filled_at, updated_at, slippage_bps) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)"
        )
        update_query = (
            "UPDATE order_states SET "
            "exchange=$4, symbol=$5, side=$6, size=$7, status=$8, "
            "order_id=COALESCE($9, order_id), client_order_id=COALESCE($10, client_order_id), "
            "reason=$11, fill_price=$12, fee_usd=$13, filled_size=$14, remaining_size=$15, "
            "state_source=$16, raw_exchange_status=$17, "
            "submitted_at=COALESCE($18, submitted_at), "
            "accepted_at=COALESCE($19, accepted_at), "
            "open_at=COALESCE($20, open_at), "
            "filled_at=COALESCE($21, filled_at), "
            "updated_at=$22, slippage_bps=COALESCE($23, slippage_bps) "
            "WHERE tenant_id=$1 AND bot_id=$2 AND {predicate}"
        )
        submitted_at = _coerce_datetime(record.submitted_at)
        accepted_at = _coerce_datetime(record.accepted_at)
        open_at = _coerce_datetime(record.open_at)
        filled_at = _coerce_datetime(record.filled_at)
        updated_at = _coerce_datetime(record.updated_at)
        async with self.pool.acquire() as conn:
            if record.client_order_id:
                result = await conn.execute(
                    update_query.format(predicate="client_order_id=$3"),
                    record.tenant_id,
                    record.bot_id,
                    record.client_order_id,
                    record.exchange,
                    record.symbol,
                    record.side,
                    record.size,
                    record.status,
                    record.order_id,
                    record.client_order_id,
                    record.reason,
                    record.fill_price,
                    record.fee_usd,
                    record.filled_size,
                    record.remaining_size,
                    record.state_source,
                    record.raw_exchange_status,
                    submitted_at,
                    accepted_at,
                    open_at,
                    filled_at,
                    updated_at,
                    record.slippage_bps,
                )
                if _rows_affected(result) > 0:
                    return
            if record.order_id:
                result = await conn.execute(
                    update_query.format(predicate="order_id=$3"),
                    record.tenant_id,
                    record.bot_id,
                    record.order_id,
                    record.exchange,
                    record.symbol,
                    record.side,
                    record.size,
                    record.status,
                    record.order_id,
                    record.client_order_id,
                    record.reason,
                    record.fill_price,
                    record.fee_usd,
                    record.filled_size,
                    record.remaining_size,
                    record.state_source,
                    record.raw_exchange_status,
                    submitted_at,
                    accepted_at,
                    open_at,
                    filled_at,
                    updated_at,
                    record.slippage_bps,
                )
                if _rows_affected(result) > 0:
                    return
            try:
                await conn.execute(
                    query,
                    record.tenant_id,
                    record.bot_id,
                    record.exchange,
                    record.symbol,
                    record.side,
                    record.size,
                    record.status,
                    record.order_id,
                    record.client_order_id,
                    record.reason,
                    record.fill_price,
                    record.fee_usd,
                    record.filled_size,
                    record.remaining_size,
                    record.state_source,
                    record.raw_exchange_status,
                    submitted_at,
                    accepted_at,
                    open_at,
                    filled_at,
                    updated_at,
                    record.slippage_bps,
                )
            except asyncpg.UniqueViolationError:
                # If a unique index exists in some environments, retry as update.
                if record.client_order_id:
                    retry_result = await conn.execute(
                        update_query.format(predicate="client_order_id=$3"),
                        record.tenant_id,
                        record.bot_id,
                        record.client_order_id,
                        record.exchange,
                        record.symbol,
                        record.side,
                        record.size,
                        record.status,
                        record.order_id,
                        record.client_order_id,
                        record.reason,
                        record.fill_price,
                        record.fee_usd,
                        record.filled_size,
                        record.remaining_size,
                        record.state_source,
                        record.raw_exchange_status,
                        submitted_at,
                        accepted_at,
                        open_at,
                        filled_at,
                        updated_at,
                        record.slippage_bps,
                    )
                    if _rows_affected(retry_result) > 0:
                        return
                if record.order_id:
                    await conn.execute(
                        update_query.format(predicate="order_id=$3"),
                        record.tenant_id,
                        record.bot_id,
                        record.order_id,
                        record.exchange,
                        record.symbol,
                        record.side,
                        record.size,
                        record.status,
                        record.order_id,
                        record.client_order_id,
                        record.reason,
                        record.fill_price,
                        record.fee_usd,
                        record.filled_size,
                        record.remaining_size,
                        record.state_source,
                        record.raw_exchange_status,
                        submitted_at,
                        accepted_at,
                        open_at,
                        filled_at,
                        updated_at,
                        record.slippage_bps,
                    )

    async def write_order_event(self, record: OrderEventRecord) -> None:
        query_with_slippage = (
            "INSERT INTO order_lifecycle_events "
            "(tenant_id, bot_id, exchange, symbol, side, size, status, event_type, order_id, client_order_id, "
            "reason, fill_price, fee_usd, filled_size, remaining_size, state_source, raw_exchange_status, created_at, slippage_bps) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)"
        )
        query_without_slippage = (
            "INSERT INTO order_lifecycle_events "
            "(tenant_id, bot_id, exchange, symbol, side, size, status, event_type, order_id, client_order_id, "
            "reason, fill_price, fee_usd, filled_size, remaining_size, state_source, raw_exchange_status, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)"
        )
        telemetry_query = (
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
                          AND oe.exchange IS NOT DISTINCT FROM $4
                          AND oe.ts = $5
                          AND oe.payload = incoming.payload
                      )
                  )
            )
            """
        )
        event_ts = _coerce_datetime(record.created_at) or datetime.now(timezone.utc)
        telemetry_payload = json.dumps(_order_event_payload(record), separators=(",", ":"), sort_keys=True, default=str)
        telemetry_semantic_key = _order_event_semantic_key(record, event_ts)
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    query_with_slippage,
                    record.tenant_id,
                    record.bot_id,
                    record.exchange,
                    record.symbol,
                    record.side,
                    record.size,
                    record.status,
                    record.event_type,
                    record.order_id,
                    record.client_order_id,
                    record.reason,
                    record.fill_price,
                    record.fee_usd,
                    record.filled_size,
                    record.remaining_size,
                    record.state_source,
                    record.raw_exchange_status,
                    event_ts,
                    record.slippage_bps,
                )
            except asyncpg.UndefinedColumnError as exc:
                # Backward compatibility for older DBs that don't yet have slippage_bps.
                if "slippage_bps" not in str(exc):
                    raise
                await conn.execute(
                    query_without_slippage,
                    record.tenant_id,
                    record.bot_id,
                    record.exchange,
                    record.symbol,
                    record.side,
                    record.size,
                    record.status,
                    record.event_type,
                    record.order_id,
                    record.client_order_id,
                    record.reason,
                    record.fill_price,
                    record.fee_usd,
                    record.filled_size,
                    record.remaining_size,
                    record.state_source,
                    record.raw_exchange_status,
                    event_ts,
                )
            await conn.execute(
                telemetry_query,
                record.tenant_id,
                record.bot_id,
                record.symbol or None,
                record.exchange,
                event_ts,
                telemetry_payload,
                telemetry_semantic_key,
            )

    async def write_order_intent(self, record: OrderIntentRecord) -> None:
        query = (
            "INSERT INTO order_intents "
            "(intent_id, tenant_id, bot_id, decision_id, client_order_id, symbol, side, size, "
            "entry_price, stop_loss, take_profit, strategy_id, profile_id, status, order_id, "
            "last_error, created_at, submitted_at, snapshot_metrics) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19) "
            "ON CONFLICT (tenant_id, bot_id, client_order_id) DO UPDATE SET "
            "decision_id=COALESCE(EXCLUDED.decision_id, order_intents.decision_id), "
            "symbol=COALESCE(EXCLUDED.symbol, order_intents.symbol), "
            "side=COALESCE(EXCLUDED.side, order_intents.side), "
            "size=COALESCE(EXCLUDED.size, order_intents.size), "
            "entry_price=COALESCE(EXCLUDED.entry_price, order_intents.entry_price), "
            "stop_loss=COALESCE(EXCLUDED.stop_loss, order_intents.stop_loss), "
            "take_profit=COALESCE(EXCLUDED.take_profit, order_intents.take_profit), "
            "strategy_id=COALESCE(EXCLUDED.strategy_id, order_intents.strategy_id), "
            "profile_id=COALESCE(EXCLUDED.profile_id, order_intents.profile_id), "
            "status=EXCLUDED.status, "
            "order_id=COALESCE(EXCLUDED.order_id, order_intents.order_id), "
            "last_error=COALESCE(EXCLUDED.last_error, order_intents.last_error), "
            "submitted_at=COALESCE(EXCLUDED.submitted_at, order_intents.submitted_at), "
            "snapshot_metrics=COALESCE(EXCLUDED.snapshot_metrics, order_intents.snapshot_metrics)"
        )
        # Convert snapshot_metrics dict to JSON string for JSONB column
        import json
        snapshot_json = json.dumps(record.snapshot_metrics) if record.snapshot_metrics else None
        
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                record.intent_id,
                record.tenant_id,
                record.bot_id,
                record.decision_id,
                record.client_order_id,
                record.symbol,
                record.side,
                record.size,
                record.entry_price,
                record.stop_loss,
                record.take_profit,
                record.strategy_id,
                record.profile_id,
                record.status,
                record.order_id,
                record.last_error,
                _coerce_datetime(record.created_at),
                _coerce_datetime(record.submitted_at),
                snapshot_json,
            )

    async def load_pending_intents(self, tenant_id: str, bot_id: str) -> list[dict]:
        query = (
            "SELECT intent_id, decision_id, client_order_id, symbol, side, size, entry_price, stop_loss, "
            "take_profit, strategy_id, profile_id, status, order_id, last_error, created_at, submitted_at "
            "FROM order_intents WHERE tenant_id=$1 AND bot_id=$2 AND status IN ('created', 'submitted', 'pending')"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, bot_id)
        return [dict(row) for row in rows]

    async def load_intent_by_client_order_id(
        self, tenant_id: str, bot_id: str, client_order_id: str
    ) -> Optional[dict]:
        query = (
            "SELECT intent_id, decision_id, client_order_id, symbol, side, size, entry_price, stop_loss, "
            "take_profit, strategy_id, profile_id, status, order_id, last_error, created_at, submitted_at "
            "FROM order_intents WHERE tenant_id=$1 AND bot_id=$2 AND client_order_id=$3"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, tenant_id, bot_id, client_order_id)
        return dict(row) if row else None

    async def expire_stale_intents(
        self, tenant_id: str, bot_id: str, max_age_sec: float = 60.0
    ) -> int:
        """Mark stale intents as 'expired' if stuck in 'created' or 'submitted' state.
        
        Returns the number of intents expired.
        """
        query = (
            "UPDATE order_intents oi SET status='expired', last_error='TTL_EXCEEDED' "
            "WHERE oi.tenant_id=$1 AND oi.bot_id=$2 "
            "AND oi.status IN ('created', 'submitted', 'pending') "
            "AND oi.created_at < NOW() - INTERVAL '1 second' * $3 "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM order_states os "
            "  WHERE os.tenant_id = oi.tenant_id "
            "    AND os.bot_id = oi.bot_id "
            "    AND os.client_order_id = oi.client_order_id "
            "    AND os.status NOT IN ('created', 'submitted', 'pending')"
            ")"
        )
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, tenant_id, bot_id, max_age_sec)
        # result is like "UPDATE N"
        try:
            return int(result.split()[-1])
        except (IndexError, ValueError):
            return 0

    async def write_order_error(self, record: OrderErrorRecord) -> None:
        query = (
            "INSERT INTO order_errors "
            "(error_id, tenant_id, bot_id, exchange, symbol, order_id, client_order_id, stage, "
            "error_code, error_message, payload, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                record.error_id,
                record.tenant_id,
                record.bot_id,
                record.exchange,
                record.symbol,
                record.order_id,
                record.client_order_id,
                record.stage,
                record.error_code,
                record.error_message,
                record.payload,
                _coerce_datetime(record.created_at),
            )

    async def write_trade_cost(self, record: TradeCostRecord) -> None:
        query = (
            "INSERT INTO trade_costs "
            "(trade_id, symbol, profile_id, execution_price, decision_mid_price, slippage_bps, "
            "fees, funding_cost, total_cost, order_size, side, timestamp, "
            "entry_fee_usd, exit_fee_usd, entry_fee_bps, exit_fee_bps, "
            "entry_slippage_bps, exit_slippage_bps, spread_cost_bps, adverse_selection_bps, total_cost_bps) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                record.trade_id,
                record.symbol,
                record.profile_id,
                record.execution_price,
                record.decision_mid_price,
                record.slippage_bps,
                record.fees,
                record.funding_cost,
                record.total_cost,
                record.order_size,
                record.side,
                _coerce_datetime(record.timestamp),
                record.entry_fee_usd,
                record.exit_fee_usd,
                record.entry_fee_bps,
                record.exit_fee_bps,
                record.entry_slippage_bps,
                record.exit_slippage_bps,
                record.spread_cost_bps,
                record.adverse_selection_bps,
                record.total_cost_bps,
            )

    async def load_latest(self, tenant_id: str, bot_id: str) -> list[dict]:
        query = (
            "SELECT symbol, side, size, status, order_id, client_order_id, reason, "
            "fill_price, fee_usd, filled_size, remaining_size, updated_at "
            "FROM order_states WHERE tenant_id=$1 AND bot_id=$2"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, bot_id)
        return [dict(row) for row in rows]

    async def load_order_events(
        self,
        tenant_id: str,
        bot_id: str,
        since: Optional[datetime],
        limit: int,
    ) -> list[dict]:
        if since:
            query = (
                "SELECT exchange, symbol, side, size, status, event_type, order_id, client_order_id, reason, "
                "fill_price, fee_usd, filled_size, remaining_size, state_source, raw_exchange_status, created_at "
                "FROM order_lifecycle_events WHERE tenant_id=$1 AND bot_id=$2 AND created_at >= $3 "
                "ORDER BY created_at ASC LIMIT $4"
            )
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, tenant_id, bot_id, since, limit)
        else:
            query = (
                "SELECT exchange, symbol, side, size, status, event_type, order_id, client_order_id, reason, "
                "fill_price, fee_usd, filled_size, remaining_size, state_source, raw_exchange_status, created_at "
                "FROM order_lifecycle_events WHERE tenant_id=$1 AND bot_id=$2 "
                "ORDER BY created_at ASC LIMIT $3"
            )
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, tenant_id, bot_id, limit)
        return [dict(row) for row in rows]


@dataclass(frozen=True)
class IdempotencyAuditRecord:
    tenant_id: str
    bot_id: str
    client_order_id: str
    status: str
    created_at: str
    expires_at: Optional[str] = None
    reason: Optional[str] = None


class PostgresIdempotencyStore:
    """Persist idempotency claims for audit."""

    def __init__(self, pool):
        self.pool = pool

    async def write_audit(self, record: IdempotencyAuditRecord) -> None:
        query = (
            "INSERT INTO idempotency_audit "
            "(tenant_id, bot_id, client_order_id, status, created_at, expires_at, reason) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7)"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                record.tenant_id,
                record.bot_id,
                record.client_order_id,
                record.status,
                _coerce_datetime(record.created_at),
                _coerce_datetime(record.expires_at),
                record.reason,
            )

    async def is_claimed(self, tenant_id: str, bot_id: str, client_order_id: str) -> bool:
        query = (
            "SELECT status, expires_at FROM idempotency_audit "
            "WHERE tenant_id=$1 AND bot_id=$2 AND client_order_id=$3 "
            "ORDER BY created_at DESC LIMIT 1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, tenant_id, bot_id, client_order_id)
        if not row:
            return False
        status = row.get("status") if isinstance(row, dict) else row["status"]
        expires_at = row.get("expires_at") if isinstance(row, dict) else row["expires_at"]
        if status != "claimed" or not expires_at:
            return False
        try:
            expires_ts = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        return expires_ts >= datetime.now(timezone.utc)

    async def load_recent_claims(
        self,
        tenant_id: str,
        bot_id: str,
        since: Optional[datetime],
        limit: int,
    ) -> list[dict]:
        if since:
            query = (
                "SELECT client_order_id, status, created_at, expires_at "
                "FROM idempotency_audit WHERE tenant_id=$1 AND bot_id=$2 AND created_at >= $3 "
                "ORDER BY created_at ASC LIMIT $4"
            )
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, tenant_id, bot_id, since, limit)
        else:
            query = (
                "SELECT client_order_id, status, created_at, expires_at "
                "FROM idempotency_audit WHERE tenant_id=$1 AND bot_id=$2 "
                "ORDER BY created_at ASC LIMIT $3"
            )
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, tenant_id, bot_id, limit)
        return [dict(row) for row in rows]


def _coerce_datetime(value: Optional[object]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _rows_affected(result: str) -> int:
    try:
        return int(str(result).split()[-1])
    except Exception:
        return 0


def _order_event_payload(record: OrderEventRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant_id": record.tenant_id,
        "bot_id": record.bot_id,
        "exchange": record.exchange,
        "symbol": record.symbol,
        "side": record.side,
        "size": record.size,
        "status": record.status,
        "event_type": record.event_type,
        "order_id": record.order_id,
        "client_order_id": record.client_order_id,
        "reason": record.reason,
        "fill_price": record.fill_price,
        "fee_usd": record.fee_usd,
        "filled_size": record.filled_size,
        "remaining_size": record.remaining_size,
        "state_source": record.state_source,
        "raw_exchange_status": record.raw_exchange_status,
        "slippage_bps": record.slippage_bps,
        "ts": (_coerce_datetime(record.created_at) or datetime.now(timezone.utc)).isoformat(),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _order_event_semantic_key(record: OrderEventRecord, event_ts: datetime) -> str:
    stable_parts = (
        record.order_id or "",
        record.client_order_id or "",
        record.symbol or "",
        record.exchange or "",
        record.status or "",
        record.event_type or "",
        event_ts.isoformat(),
    )
    return "|".join(stable_parts)
