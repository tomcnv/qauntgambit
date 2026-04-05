# Live Readiness Checklist

Status tags:
- [ ] Not done
- [~] Implemented but needs live validation
- [x] Done

## Critical blockers before live test
- [ ] Private WS order updates (Binance + OKX): capture live fixtures for filled/partial/canceled/TP/SL/RO; add schema validation; map close metadata; ensure reconciliation feeds authoritative order/position snapshots for UI. (Using Binance NEW/EXPIRED stop/TP fixtures for now; FILLED stop/TP still pending live capture.)
- [x] Risk sizing depth parity (live): runtime risk limits/exposure/remaining match dashboard UI values under live adapter; add validation harness reading `/api/runtime/risk` + `/api/dashboard/risk` during live orders.
- [x] Market data resiliency in live mode: WS gap -> resync -> feature gating with real feeds; `/api/runtime/quality` returns sync states + quality scores with live feeds.
- [x] Durable recovery end-to-end: run real-services harness against local Redis + Timescale/Postgres; restart restores orders/positions to dashboard snapshots.

## High-priority correctness/observability
- [x] Config drift guardrails: emit banner/alert payload when runtime config diverges from stored config; surface in UI.
- [x] Idempotency durability alerts: emit alert if Redis is down so dedupe guarantees are degraded.
- [x] Risk overrides TTL cleanup: periodic prune + telemetry on stale override drops.

## Exchange coverage
- [x] Binance testnet WS capture: private WS payloads for order lifecycle states; fixtures/tests aligned with OKX.
- [x] OKX TP/SL native flow: ensure protective order payloads are captured and mapped correctly (algo fields).

## Dashboard/API integration
- [x] Endpoint parity: all UI pages have bot endpoints with stable response shapes; update migration docs.
- [x] Telemetry contract docs: guardrail/prediction suppression/data quality payloads documented and consumed by UI panels.

## Backtest/replay exports
- [x] Exports alignment: backtest/replay outputs map to Timescale schema and are exposed via API for dashboard history + PnL + prediction labels.
