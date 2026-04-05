"""Execution simulator for backtesting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple


@dataclass
class SimPosition:
    symbol: str
    side: str
    size: float
    entry_price: float
    raw_entry_price: float
    entry_fee: float
    profile_id: Optional[str] = None
    strategy_id: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class SimResult:
    equity: float
    realized_pnl: float
    open_positions: int


@dataclass(frozen=True)
class SimTrade:
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    entry_fee: float
    exit_fee: float
    total_fees: float
    entry_slippage_bps: float
    exit_slippage_bps: float
    profile_id: Optional[str] = None
    strategy_id: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class SimReport:
    realized_pnl: float
    total_fees: float
    total_trades: int
    win_rate: float
    max_drawdown_pct: float
    avg_slippage_bps: float
    total_return_pct: float
    profit_factor: float
    avg_trade_pnl: float


@dataclass(frozen=True)
class FeeModel:
    taker_bps: float = 1.0

    def estimate_fee(self, price: float, size: float) -> float:
        return abs(price * size) * (self.taker_bps / 10000.0)


@dataclass(frozen=True)
class TieredFeeModel:
    tiers: Sequence[Tuple[float, float]]
    default_bps: float = 1.0

    def estimate_fee(self, price: float, size: float) -> float:
        notional = abs(price * size)
        bps = self.default_bps
        for threshold, tier_bps in self.tiers:
            if notional >= threshold:
                bps = tier_bps
            else:
                break
        return notional * (bps / 10000.0)


@dataclass(frozen=True)
class SlippageModel:
    slippage_bps: float = 0.0
    impact_bps: float = 0.0
    max_slippage_bps: float = 0.0

    def apply(
        self,
        price: float,
        side: str,
        size: Optional[float] = None,
        depth_usd: Optional[float] = None,
        volatility_ratio: Optional[float] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
    ) -> float:
        base_price = _base_price(price, side, bid, ask)
        slip_bps = self.slippage_bps + self._impact_slippage_bps(base_price, size, depth_usd)
        if self.max_slippage_bps > 0:
            slip_bps = min(slip_bps, self.max_slippage_bps)
        slip = slip_bps / 10000.0
        normalized = (side or "").lower()
        if normalized in ("buy", "long"):
            return base_price * (1 + slip)
        if normalized in ("sell", "short"):
            return base_price * (1 - slip)
        return base_price

    def bps(self, raw_price: float, fill_price: float) -> float:
        if raw_price <= 0:
            return 0.0
        return abs((fill_price - raw_price) / raw_price) * 10000.0

    def _impact_slippage_bps(
        self,
        price: float,
        size: Optional[float],
        depth_usd: Optional[float],
    ) -> float:
        if not self.impact_bps or not size or not depth_usd or depth_usd <= 0:
            return 0.0
        notional = abs(size * price)
        impact_ratio = notional / depth_usd
        return self.impact_bps * impact_ratio


@dataclass(frozen=True)
class VolatilitySlippageModel(SlippageModel):
    volatility_bps: float = 0.0
    volatility_ratio_cap: float = 2.0

    def apply(
        self,
        price: float,
        side: str,
        size: Optional[float] = None,
        depth_usd: Optional[float] = None,
        volatility_ratio: Optional[float] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
    ) -> float:
        base_price = _base_price(price, side, bid, ask)
        slip_bps = (
            self.slippage_bps
            + self._impact_slippage_bps(base_price, size, depth_usd)
            + self._volatility_slippage_bps(volatility_ratio)
        )
        if self.max_slippage_bps > 0:
            slip_bps = min(slip_bps, self.max_slippage_bps)
        slip = slip_bps / 10000.0
        normalized = (side or "").lower()
        if normalized in ("buy", "long"):
            return base_price * (1 + slip)
        if normalized in ("sell", "short"):
            return base_price * (1 - slip)
        return base_price

    def _volatility_slippage_bps(self, volatility_ratio: Optional[float]) -> float:
        if not self.volatility_bps or volatility_ratio is None:
            return 0.0
        ratio = max(0.0, volatility_ratio)
        if self.volatility_ratio_cap > 0:
            ratio = min(ratio, self.volatility_ratio_cap)
        extra = max(0.0, ratio - 1.0)
        return self.volatility_bps * extra


class ExecutionSimulator:
    """Simple simulator for position PnL."""

    def __init__(
        self,
        starting_equity: float = 10000.0,
        fee_model: Optional[FeeModel] = None,
        slippage_model: Optional[SlippageModel] = None,
    ):
        self.starting_equity = starting_equity
        self.equity = starting_equity
        self.realized_pnl = 0.0
        self.symbol_realized_pnl: Dict[str, float] = {}
        self.positions: Dict[str, SimPosition] = {}
        self.fee_model = fee_model or FeeModel()
        self.slippage_model = slippage_model or SlippageModel()
        self.total_fees = 0.0
        self.trades: list[SimTrade] = []
        self.equity_peak = starting_equity
        self.max_drawdown_pct = 0.0

    def apply_signal(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        bid_depth_usd: Optional[float] = None,
        ask_depth_usd: Optional[float] = None,
        volatility_ratio: Optional[float] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        profile_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        existing = self.positions.get(symbol)
        if existing and existing.side != side:
            exit_depth = _depth_for_side(_exit_side(existing.side), bid_depth_usd, ask_depth_usd)
            self._close(
                symbol,
                price,
                depth_usd=exit_depth,
                volatility_ratio=volatility_ratio,
                bid=bid,
                ask=ask,
            )
        if symbol not in self.positions:
            entry_depth = _depth_for_side(side, bid_depth_usd, ask_depth_usd)
            fill_price = self.slippage_model.apply(
                price,
                side,
                size=size,
                depth_usd=entry_depth,
                volatility_ratio=volatility_ratio,
                bid=bid,
                ask=ask,
            )
            fee = self.fee_model.estimate_fee(fill_price, size)
            self.realized_pnl -= fee
            self.total_fees += fee
            self.symbol_realized_pnl[symbol] = self.symbol_realized_pnl.get(symbol, 0.0) - fee
            self.positions[symbol] = SimPosition(
                symbol=symbol,
                side=side,
                size=size,
                entry_price=fill_price,
                raw_entry_price=price,
                entry_fee=fee,
                profile_id=profile_id,
                strategy_id=strategy_id,
                reason=reason,
            )

    def mark_to_market(self, prices: Dict[str, float]) -> SimResult:
        equity = self.starting_equity + self.realized_pnl
        for symbol, pos in self.positions.items():
            price = prices.get(symbol)
            if price is None:
                continue
            pnl = (price - pos.entry_price) * pos.size
            if pos.side in ("short", "sell"):
                pnl *= -1
            equity += pnl
        self.equity = equity
        if equity > self.equity_peak:
            self.equity_peak = equity
        if self.equity_peak > 0:
            drawdown_pct = ((self.equity_peak - equity) / self.equity_peak) * 100.0
            if drawdown_pct > self.max_drawdown_pct:
                self.max_drawdown_pct = drawdown_pct
        return SimResult(equity=equity, realized_pnl=self.realized_pnl, open_positions=len(self.positions))

    def close_all(self, prices: Dict[str, float]) -> None:
        for symbol in list(self.positions.keys()):
            price = prices.get(symbol)
            if price is None:
                continue
            self._close(symbol, price, depth_usd=None, volatility_ratio=None)

    def _close(
        self,
        symbol: str,
        price: float,
        depth_usd: Optional[float],
        volatility_ratio: Optional[float],
        bid: Optional[float] = None,
        ask: Optional[float] = None,
    ) -> None:
        pos = self.positions.pop(symbol, None)
        if not pos:
            return
        exit_side = _exit_side(pos.side)
        exit_price = self.slippage_model.apply(
            price,
            exit_side,
            size=pos.size,
            depth_usd=depth_usd,
            volatility_ratio=volatility_ratio,
            bid=bid,
            ask=ask,
        )
        pnl = (exit_price - pos.entry_price) * pos.size
        if pos.side in ("short", "sell"):
            pnl *= -1
        exit_fee = self.fee_model.estimate_fee(exit_price, pos.size)
        entry_fee = pos.entry_fee
        total_fees = entry_fee + exit_fee
        self.realized_pnl += pnl - exit_fee
        self.total_fees += exit_fee
        self.symbol_realized_pnl[symbol] = self.symbol_realized_pnl.get(symbol, 0.0) + pnl - exit_fee
        entry_slippage = self.slippage_model.bps(pos.raw_entry_price, pos.entry_price)
        exit_slippage = self.slippage_model.bps(price, exit_price)
        self.trades.append(
            SimTrade(
                symbol=pos.symbol,
                side=pos.side,
                size=pos.size,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                pnl=pnl - total_fees,
                entry_fee=entry_fee,
                exit_fee=exit_fee,
                total_fees=total_fees,
                entry_slippage_bps=entry_slippage,
                exit_slippage_bps=exit_slippage,
                profile_id=pos.profile_id,
                strategy_id=pos.strategy_id,
                reason=pos.reason,
            )
        )

    def report(self) -> SimReport:
        total_trades = len(self.trades)
        wins = len([trade for trade in self.trades if trade.pnl > 0])
        win_rate = (wins / total_trades) if total_trades else 0.0
        slippage_values = [
            (trade.entry_slippage_bps + trade.exit_slippage_bps) / 2.0 for trade in self.trades
        ]
        avg_slippage = (sum(slippage_values) / len(slippage_values)) if slippage_values else 0.0
        gross_profit = sum(trade.pnl for trade in self.trades if trade.pnl > 0)
        gross_loss = sum(abs(trade.pnl) for trade in self.trades if trade.pnl < 0)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
        avg_trade_pnl = (self.realized_pnl / total_trades) if total_trades else 0.0
        total_return_pct = (self.realized_pnl / self.starting_equity * 100.0) if self.starting_equity else 0.0
        return SimReport(
            realized_pnl=self.realized_pnl,
            total_fees=self.total_fees,
            total_trades=total_trades,
            win_rate=win_rate,
            max_drawdown_pct=self.max_drawdown_pct,
            avg_slippage_bps=avg_slippage,
            total_return_pct=total_return_pct,
            profit_factor=profit_factor,
            avg_trade_pnl=avg_trade_pnl,
        )


def _exit_side(side: str) -> str:
    normalized = (side or "").lower()
    if normalized in ("buy", "long"):
        return "sell"
    if normalized in ("sell", "short"):
        return "buy"
    return "sell"


def _depth_for_side(side: str, bid_depth: Optional[float], ask_depth: Optional[float]) -> Optional[float]:
    normalized = (side or "").lower()
    if normalized in ("buy", "long"):
        return ask_depth
    if normalized in ("sell", "short"):
        return bid_depth
    return None


def _base_price(price: float, side: str, bid: Optional[float], ask: Optional[float]) -> float:
    if bid is None or ask is None:
        return price
    normalized = (side or "").lower()
    if normalized in ("buy", "long"):
        return ask
    if normalized in ("sell", "short"):
        return bid
    return price
