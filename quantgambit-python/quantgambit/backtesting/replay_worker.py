"""Replay worker for backtesting feature snapshots."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from quantgambit.observability.logger import log_info, log_warning
from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput
from quantgambit.backtesting.simulator import (
    ExecutionSimulator,
    FeeModel,
    SlippageModel,
    TieredFeeModel,
    VolatilitySlippageModel,
)
from quantgambit.backtesting.store import (
    BacktestStore,
    BacktestRunRecord,
    BacktestMetricsRecord,
    BacktestTradeRecord,
    BacktestEquityPoint,
    BacktestSymbolEquityPoint,
    BacktestSymbolMetricsRecord,
    BacktestDecisionSnapshot,
    BacktestPositionSnapshot,
)


@dataclass
class ReplayConfig:
    input_path: Path
    sleep_ms: int = 0
    latency_ms: int = 0
    fee_bps: float = 1.0
    fee_model: str = "flat"
    fee_tiers: list[dict] = field(default_factory=list)
    slippage_bps: float = 0.0
    impact_bps: float = 0.0
    max_slippage_bps: float = 0.0
    slippage_model: str = "flat"
    volatility_bps: float = 0.0
    volatility_ratio_cap: float = 2.0
    equity_sample_every: int = 1
    max_equity_points: int = 2000
    max_symbol_equity_points: int = 2000
    max_decision_snapshots: int = 2000
    max_position_snapshots: int = 2000
    warmup_min_snapshots: int = 0
    warmup_require_ready: bool = False
    run_id: Optional[str] = None
    tenant_id: Optional[str] = None
    bot_id: Optional[str] = None

    @classmethod
    def from_env(cls, input_path: Path) -> "ReplayConfig":
        return cls(
            input_path=input_path,
            sleep_ms=int(os.getenv("BACKTEST_SLEEP_MS", "0")),
            latency_ms=int(os.getenv("BACKTEST_LATENCY_MS", "0")),
            fee_bps=float(os.getenv("BACKTEST_FEE_BPS", "1.0")),
            fee_model=os.getenv("BACKTEST_FEE_MODEL", "flat").lower(),
            fee_tiers=_parse_fee_tiers(os.getenv("BACKTEST_FEE_TIERS", "[]")),
            slippage_bps=float(os.getenv("BACKTEST_SLIPPAGE_BPS", "0.0")),
            impact_bps=float(os.getenv("BACKTEST_IMPACT_BPS", "0.0")),
            max_slippage_bps=float(os.getenv("BACKTEST_MAX_SLIPPAGE_BPS", "0.0")),
            slippage_model=os.getenv("BACKTEST_SLIPPAGE_MODEL", "flat").lower(),
            volatility_bps=float(os.getenv("BACKTEST_VOLATILITY_BPS", "0.0")),
            volatility_ratio_cap=float(os.getenv("BACKTEST_VOLATILITY_RATIO_CAP", "2.0")),
            equity_sample_every=int(os.getenv("BACKTEST_EQUITY_SAMPLE_EVERY", "1")),
            max_equity_points=int(os.getenv("BACKTEST_MAX_EQUITY_POINTS", "2000")),
            max_symbol_equity_points=int(os.getenv("BACKTEST_MAX_SYMBOL_EQUITY_POINTS", "2000")),
            max_decision_snapshots=int(os.getenv("BACKTEST_MAX_DECISION_SNAPSHOTS", "2000")),
            max_position_snapshots=int(os.getenv("BACKTEST_MAX_POSITION_SNAPSHOTS", "2000")),
            warmup_min_snapshots=int(os.getenv("BACKTEST_WARMUP_SNAPSHOTS", "0")),
            warmup_require_ready=os.getenv("BACKTEST_WARMUP_REQUIRE_READY", "false").lower() in {"1", "true", "yes"},
            run_id=os.getenv("BACKTEST_RUN_ID"),
            tenant_id=os.getenv("TENANT_ID"),
            bot_id=os.getenv("BOT_ID"),
        )


class ReplayWorker:
    """Replays feature snapshots from a JSONL file."""

    def __init__(
        self,
        engine: DecisionEngine,
        config: ReplayConfig,
        simulate: bool = False,
        starting_equity: float = 10000.0,
        backtest_store: Optional[BacktestStore] = None,
    ):
        self.engine = engine
        self.config = config
        self.simulate = simulate
        self.simulator = (
            ExecutionSimulator(
                starting_equity=starting_equity,
                fee_model=_build_fee_model(config),
                slippage_model=_build_slippage_model(config),
            )
            if simulate
            else None
        )
        self.last_report = None
        self.backtest_store = backtest_store

    def get_report(self):
        return self.last_report

    async def run(self) -> list[dict]:
        log_info("replay_worker_start", path=str(self.config.input_path))
        results: list[dict] = []
        started_at = _now_iso()
        run_id = self.config.run_id
        last_prices: dict[str, float] = {}
        pending_signals: list[dict] = []
        equity_points: list[BacktestEquityPoint] = []
        symbol_equity_points: list[BacktestSymbolEquityPoint] = []
        decision_snapshots: list[BacktestDecisionSnapshot] = []
        position_snapshots: list[BacktestPositionSnapshot] = []
        warnings: list[str] = []
        missing_price_count = 0
        missing_depth_count = 0
        warmup_skipped = 0
        if self.backtest_store and run_id and self.config.tenant_id and self.config.bot_id:
            await self.backtest_store.write_run(
                BacktestRunRecord(
                    run_id=run_id,
                    tenant_id=self.config.tenant_id,
                    bot_id=self.config.bot_id,
                    status="running",
                    started_at=started_at,
                    finished_at=None,
                    config={
                        "input_path": str(self.config.input_path),
                        "fee_bps": self.config.fee_bps,
                        "fee_model": self.config.fee_model,
                        "fee_tiers": self.config.fee_tiers,
                        "slippage_bps": self.config.slippage_bps,
                        "slippage_model": self.config.slippage_model,
                        "volatility_bps": self.config.volatility_bps,
                        "volatility_ratio_cap": self.config.volatility_ratio_cap,
                        "starting_equity": self.simulator.starting_equity if self.simulator else None,
                        "equity_sample_every": self.config.equity_sample_every,
                        "max_equity_points": self.config.max_equity_points,
                        "max_symbol_equity_points": self.config.max_symbol_equity_points,
                        "max_decision_snapshots": self.config.max_decision_snapshots,
                        "max_position_snapshots": self.config.max_position_snapshots,
                        "warmup_min_snapshots": self.config.warmup_min_snapshots,
                        "warmup_require_ready": self.config.warmup_require_ready,
                    },
                )
            )
        for idx, snapshot in enumerate(_load_snapshots(self.config.input_path), start=1):
            if self.simulator and pending_signals:
                pending_signals = self._execute_pending_signals(pending_signals, snapshot)
                missing_depth_count += getattr(self, "_missing_depth_count", 0)
                self._missing_depth_count = 0
            warmup_ready = snapshot.get("warmup_ready")
            if idx <= self.config.warmup_min_snapshots or (
                self.config.warmup_require_ready and warmup_ready is False
            ):
                warmup_skipped += 1
                price = _snapshot_price(snapshot)
                if price is not None:
                    last_prices[snapshot["symbol"]] = price
                results.append({
                    "symbol": snapshot["symbol"],
                    "timestamp": snapshot.get("timestamp"),
                    "decision": "warmup",
                    "rejection_reason": "warmup",
                    "profile_id": None,
                    "equity": self.simulator.equity if self.simulator else None,
                    "realized_pnl": self.simulator.realized_pnl if self.simulator else None,
                    "open_positions": len(self.simulator.positions) if self.simulator else None,
                })
                if self.config.sleep_ms:
                    await asyncio.sleep(self.config.sleep_ms / 1000.0)
                continue
            # Build market_context with best_bid/best_ask for EV gate
            market_context = snapshot.get("market_context") or {}
            features = snapshot.get("features") or {}
            
            # Add best_bid/best_ask from bid/ask if not present (required by EV gate)
            if "best_bid" not in market_context and "bid" in market_context:
                market_context["best_bid"] = market_context["bid"]
            if "best_ask" not in market_context and "ask" in market_context:
                market_context["best_ask"] = market_context["ask"]
            if "best_bid" not in features and "bid" in features:
                features["best_bid"] = features["bid"]
            if "best_ask" not in features and "ask" in features:
                features["best_ask"] = features["ask"]
            
            # Build prediction dict with default confidence if not present
            # The EV gate requires prediction.confidence for EV calculation
            prediction = snapshot.get("prediction") or {}
            if "confidence" not in prediction:
                prediction = {
                    "confidence": 0.5,  # Default 50% confidence for backtesting
                    "direction": "neutral",
                    "source": "backtest_default",
                }
            
            decision_input = DecisionInput(
                symbol=snapshot["symbol"],
                market_context=market_context,
                features=features,
                account_state=_sim_account_state(self.simulator),
                positions=_sim_positions(self.simulator),
                prediction=prediction,
            )
            accepted, ctx = await self.engine.decide_with_context(decision_input)
            price = _snapshot_price(snapshot)
            if price is None:
                missing_price_count += 1
                if "missing_price" not in warnings:
                    warnings.append("missing_price")
            if self.simulator and accepted and ctx.signal and price is not None:
                signal = ctx.signal if isinstance(ctx.signal, dict) else {}
                side = signal.get("side")
                size = signal.get("size", 0.0)
                if side and size:
                    decision_ts = float(snapshot.get("timestamp") or 0.0)
                    latency_sec = max(self.config.latency_ms / 1000.0, 1e-9)
                    pending_signals.append(
                        {
                            "t_exec": decision_ts + latency_sec,
                            "symbol": snapshot["symbol"],
                            "side": side,
                            "size": size,
                            "profile_id": ctx.profile_id,
                            "strategy_id": signal.get("strategy_id"),
                            "reason": signal.get("reason") or "signal",
                        }
                    )
            if self.simulator:
                prices = {snapshot["symbol"]: price} if price is not None else {}
                sim = self.simulator.mark_to_market(prices)
                if price is not None:
                    last_prices[snapshot["symbol"]] = price
                if run_id and self.config.equity_sample_every > 0 and idx % self.config.equity_sample_every == 0:
                    equity_points.append(
                        BacktestEquityPoint(
                            run_id=run_id,
                            ts=_now_iso(),
                            equity=sim.equity,
                            realized_pnl=sim.realized_pnl,
                            open_positions=sim.open_positions,
                        )
                    )
                    symbol_equity_points.extend(
                        _build_symbol_equity_points(
                            run_id=run_id,
                            simulator=self.simulator,
                            prices=last_prices,
                            ts=_now_iso(),
                        )
                    )
                if run_id and self.config.equity_sample_every > 0 and idx % self.config.equity_sample_every == 0:
                    decision_snapshots.append(
                        BacktestDecisionSnapshot(
                            run_id=run_id,
                            ts=_now_iso(),
                            symbol=snapshot["symbol"],
                            decision="accepted" if accepted else "rejected",
                            rejection_reason=ctx.rejection_reason,
                            profile_id=ctx.profile_id,
                            payload={
                                "signal": ctx.signal,
                                "strategy_id": (ctx.signal or {}).get("strategy_id") if isinstance(ctx.signal, dict) else None,
                                "equity": sim.equity,
                                "realized_pnl": sim.realized_pnl,
                                "open_positions": sim.open_positions,
                                "market_context": snapshot.get("market_context") or {},
                                "features": snapshot.get("features") or {},
                            },
                        )
                    )
                    positions_payload = [
                        {
                            "symbol": pos.symbol,
                            "side": pos.side,
                            "size": pos.size,
                            "entry_price": pos.entry_price,
                        }
                        for pos in self.simulator.positions.values()
                    ]
                    position_snapshots.append(
                        BacktestPositionSnapshot(
                            run_id=run_id,
                            ts=_now_iso(),
                            payload={
                                "positions": positions_payload,
                                "equity": sim.equity,
                                "realized_pnl": sim.realized_pnl,
                                "open_positions": sim.open_positions,
                            },
                        )
                    )
            results.append({
                "symbol": snapshot["symbol"],
                "timestamp": snapshot.get("timestamp"),
                "decision": "accepted" if accepted else "rejected",
                "rejection_reason": ctx.rejection_reason,
                "profile_id": ctx.profile_id,
                "equity": sim.equity if self.simulator else None,
                "realized_pnl": sim.realized_pnl if self.simulator else None,
                "open_positions": sim.open_positions if self.simulator else None,
            })
            if self.config.sleep_ms:
                await asyncio.sleep(self.config.sleep_ms / 1000.0)
        if self.simulator:
            if last_prices:
                self.simulator.close_all(last_prices)
            self.last_report = self.simulator.report()
            if self.backtest_store and run_id and self.config.tenant_id and self.config.bot_id:
                equity_points = _cap_samples(equity_points, self.config.max_equity_points)
                symbol_equity_points = _cap_samples(symbol_equity_points, self.config.max_symbol_equity_points)
                decision_snapshots = _cap_samples(decision_snapshots, self.config.max_decision_snapshots)
                position_snapshots = _cap_samples(position_snapshots, self.config.max_position_snapshots)
                if equity_points:
                    await self.backtest_store.write_equity_points(equity_points)
                if symbol_equity_points:
                    await self.backtest_store.write_symbol_equity_points(symbol_equity_points)
                if decision_snapshots:
                    await self.backtest_store.write_decision_snapshots(decision_snapshots)
                if position_snapshots:
                    await self.backtest_store.write_position_snapshots(position_snapshots)
                await self.backtest_store.write_run(
                    BacktestRunRecord(
                        run_id=run_id,
                        tenant_id=self.config.tenant_id,
                        bot_id=self.config.bot_id,
                        status="degraded" if warnings else "finished",
                        started_at=started_at,
                        finished_at=_now_iso(),
                        config={
                            "input_path": str(self.config.input_path),
                            "fee_bps": self.config.fee_bps,
                            "fee_model": self.config.fee_model,
                            "fee_tiers": self.config.fee_tiers,
                            "slippage_bps": self.config.slippage_bps,
                            "slippage_model": self.config.slippage_model,
                            "volatility_bps": self.config.volatility_bps,
                            "volatility_ratio_cap": self.config.volatility_ratio_cap,
                            "starting_equity": self.simulator.starting_equity,
                            "equity_sample_every": self.config.equity_sample_every,
                            "max_equity_points": self.config.max_equity_points,
                            "max_symbol_equity_points": self.config.max_symbol_equity_points,
                            "max_decision_snapshots": self.config.max_decision_snapshots,
                            "max_position_snapshots": self.config.max_position_snapshots,
                            "warmup_min_snapshots": self.config.warmup_min_snapshots,
                            "warmup_require_ready": self.config.warmup_require_ready,
                            "missing_price_count": missing_price_count,
                            "missing_depth_count": missing_depth_count,
                            "warmup_skipped": warmup_skipped,
                            "warnings": warnings,
                        },
                    )
                )
                await self.backtest_store.write_metrics(
                    BacktestMetricsRecord(
                        run_id=run_id,
                        realized_pnl=self.last_report.realized_pnl,
                        total_fees=self.last_report.total_fees,
                        total_trades=self.last_report.total_trades,
                        win_rate=self.last_report.win_rate,
                        max_drawdown_pct=self.last_report.max_drawdown_pct,
                        avg_slippage_bps=self.last_report.avg_slippage_bps,
                        total_return_pct=self.last_report.total_return_pct,
                        profit_factor=self.last_report.profit_factor,
                        avg_trade_pnl=self.last_report.avg_trade_pnl,
                    )
                )
                trades = [
                    BacktestTradeRecord(
                        run_id=run_id,
                        ts=_now_iso(),
                        symbol=trade.symbol,
                        side=trade.side,
                        size=trade.size,
                        entry_price=trade.entry_price,
                        exit_price=trade.exit_price,
                        pnl=trade.pnl,
                        entry_fee=trade.entry_fee,
                        exit_fee=trade.exit_fee,
                        total_fees=trade.total_fees,
                        entry_slippage_bps=trade.entry_slippage_bps,
                        exit_slippage_bps=trade.exit_slippage_bps,
                        strategy_id=trade.strategy_id,
                        profile_id=trade.profile_id,
                        reason=trade.reason,
                    )
                    for trade in self.simulator.trades
                ]
                await self.backtest_store.write_trades(trades)
                symbol_metrics = _build_symbol_metrics(run_id, self.simulator.trades)
                if symbol_metrics:
                    await self.backtest_store.write_symbol_metrics(symbol_metrics)
        return results

    def _execute_pending_signals(self, pending: list[dict], snapshot: dict) -> list[dict]:
        if not self.simulator:
            return pending
        now_ts = float(snapshot.get("timestamp") or 0.0)
        price = _snapshot_price(snapshot)
        bid_depth, ask_depth = _snapshot_depths(snapshot)
        volatility_ratio = _snapshot_volatility_ratio(snapshot)
        bid_price, ask_price = _snapshot_bid_ask(snapshot)
        if bid_depth is None or ask_depth is None:
            # Track missing depth for reporting
            if not hasattr(self, "_missing_depth_count"):
                self._missing_depth_count = 0
            self._missing_depth_count += 1
        remaining: list[dict] = []
        for signal in pending:
            if signal["t_exec"] > now_ts:
                remaining.append(signal)
                continue
            if price is None:
                remaining.append(signal)
                continue
            self.simulator.apply_signal(
                signal["symbol"],
                signal["side"],
                signal["size"],
                price,
                bid_depth_usd=bid_depth,
                ask_depth_usd=ask_depth,
                volatility_ratio=volatility_ratio,
                bid=bid_price,
                ask=ask_price,
                profile_id=signal.get("profile_id"),
                strategy_id=signal.get("strategy_id"),
                reason=signal.get("reason"),
            )
        return remaining


def _load_snapshots(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _snapshot_price(snapshot: dict) -> Optional[float]:
    market_context = snapshot.get("market_context") or {}
    features = snapshot.get("features") or {}
    return (
        market_context.get("price")
        or features.get("price")
        or market_context.get("last")
        or features.get("last")
    )


def _snapshot_depths(snapshot: dict) -> tuple[Optional[float], Optional[float]]:
    market_context = snapshot.get("market_context") or {}
    features = snapshot.get("features") or {}
    bid_depth = market_context.get("bid_depth_usd") or features.get("bid_depth_usd")
    ask_depth = market_context.get("ask_depth_usd") or features.get("ask_depth_usd")
    return bid_depth, ask_depth


def _snapshot_bid_ask(snapshot: dict) -> tuple[Optional[float], Optional[float]]:
    market_context = snapshot.get("market_context") or {}
    features = snapshot.get("features") or {}
    bid = market_context.get("bid") or features.get("bid")
    ask = market_context.get("ask") or features.get("ask")
    return _coerce_float(bid), _coerce_float(ask)


def _sim_account_state(simulator) -> Optional[dict]:
    if simulator is None:
        return None
    return {
        "equity": simulator.equity,
        "realized_pnl": simulator.realized_pnl,
        "open_positions": len(simulator.positions),
        "max_drawdown_pct": simulator.max_drawdown_pct,
    }


def _sim_positions(simulator) -> Optional[list]:
    if simulator is None:
        return None
    positions = []
    for pos in simulator.positions.values():
        positions.append(
            {
                "symbol": pos.symbol,
                "side": pos.side,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "raw_entry_price": pos.raw_entry_price,
            }
        )
    return positions


def _snapshot_volatility_ratio(snapshot: dict) -> Optional[float]:
    market_context = snapshot.get("market_context") or {}
    features = snapshot.get("features") or {}
    atr = _coerce_float(features.get("atr_5m") or market_context.get("atr_5m"))
    baseline = _coerce_float(features.get("atr_5m_baseline") or market_context.get("atr_5m_baseline"))
    if atr and baseline:
        return atr / baseline
    regime = features.get("volatility_regime") or market_context.get("volatility_regime")
    if isinstance(regime, str):
        normalized = regime.lower()
        if normalized == "low":
            return 0.7
        if normalized == "normal":
            return 1.0
        if normalized == "high":
            return 1.3
    return None


def _build_fee_model(config: ReplayConfig) -> FeeModel:
    if config.fee_model == "tiered":
        tiers = _normalize_fee_tiers(config.fee_tiers)
        if tiers:
            return TieredFeeModel(tiers=tiers, default_bps=config.fee_bps)
        log_warning("backtest_fee_tiers_empty", fee_model=config.fee_model)
    return FeeModel(taker_bps=config.fee_bps)


def _build_slippage_model(config: ReplayConfig) -> SlippageModel:
    if config.slippage_model in {"volatility", "adaptive"}:
        return VolatilitySlippageModel(
            slippage_bps=config.slippage_bps,
            impact_bps=config.impact_bps,
            max_slippage_bps=config.max_slippage_bps,
            volatility_bps=config.volatility_bps,
            volatility_ratio_cap=config.volatility_ratio_cap,
        )
    return SlippageModel(
        slippage_bps=config.slippage_bps,
        impact_bps=config.impact_bps,
        max_slippage_bps=config.max_slippage_bps,
    )


def _normalize_fee_tiers(tiers: list[dict]) -> list[tuple[float, float]]:
    normalized: list[tuple[float, float]] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        notional = _coerce_float(tier.get("notional"))
        bps = _coerce_float(tier.get("bps"))
        if notional is None or bps is None:
            continue
        normalized.append((notional, bps))
    normalized.sort(key=lambda item: item[0])
    return normalized


def _parse_fee_tiers(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log_warning("backtest_fee_tiers_parse_failed", raw=raw)
        return []
    if not isinstance(data, list):
        log_warning("backtest_fee_tiers_invalid", raw=raw)
        return []
    return data


def _coerce_float(value: Optional[object]) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _build_symbol_metrics(run_id: str, trades: list) -> list[BacktestSymbolMetricsRecord]:
    if not trades:
        return []
    buckets: dict[str, list] = {}
    for trade in trades:
        buckets.setdefault(trade.symbol, []).append(trade)
        metrics: list[BacktestSymbolMetricsRecord] = []
    for symbol, symbol_trades in buckets.items():
        total_trades = len(symbol_trades)
        realized_pnl = sum(trade.pnl for trade in symbol_trades)
        total_fees = sum(trade.total_fees for trade in symbol_trades)
        wins = len([trade for trade in symbol_trades if trade.pnl > 0])
        win_rate = wins / total_trades if total_trades else 0.0
        avg_trade_pnl = realized_pnl / total_trades if total_trades else 0.0
        gross_profit = sum(trade.pnl for trade in symbol_trades if trade.pnl > 0)
        gross_loss = sum(abs(trade.pnl) for trade in symbol_trades if trade.pnl < 0)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
        slippage_values = [
            (trade.entry_slippage_bps + trade.exit_slippage_bps) / 2.0 for trade in symbol_trades
        ]
        avg_slippage = (sum(slippage_values) / len(slippage_values)) if slippage_values else 0.0
        metrics.append(
            BacktestSymbolMetricsRecord(
                run_id=run_id,
                symbol=symbol,
                realized_pnl=realized_pnl,
                total_fees=total_fees,
                total_trades=total_trades,
                win_rate=win_rate,
                avg_trade_pnl=avg_trade_pnl,
                profit_factor=profit_factor,
                avg_slippage_bps=avg_slippage,
            )
        )
    return metrics


def _build_symbol_equity_points(
    run_id: str,
    simulator: ExecutionSimulator,
    prices: dict[str, float],
    ts: str,
) -> list[BacktestSymbolEquityPoint]:
    symbols = set(simulator.symbol_realized_pnl) | set(simulator.positions)
    points: list[BacktestSymbolEquityPoint] = []
    for symbol in symbols:
        realized = simulator.symbol_realized_pnl.get(symbol, 0.0)
        open_pnl = 0.0
        pos = simulator.positions.get(symbol)
        price = prices.get(symbol)
        if pos and price is not None:
            open_pnl = (price - pos.entry_price) * pos.size
            if pos.side in ("short", "sell"):
                open_pnl *= -1
        equity = realized + open_pnl
        points.append(
            BacktestSymbolEquityPoint(
                run_id=run_id,
                symbol=symbol,
                ts=ts,
                equity=equity,
                realized_pnl=realized,
                open_positions=1 if pos else 0,
            )
        )
    return points


def _cap_samples(items: list, max_items: int) -> list:
    if max_items <= 0 or len(items) <= max_items:
        return items
    if max_items == 1:
        return [items[-1]]
    last_index = len(items) - 1
    step = last_index / (max_items - 1)
    indices = [int(round(step * i)) for i in range(max_items)]
    return [items[index] for index in indices]
