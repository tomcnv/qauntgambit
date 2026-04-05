"""
Fee Model - Calculate trading fees and breakeven thresholds.

CRITICAL: Without proper fee modeling, strategies will lose money.
This module ensures exit decisions consider round-trip fees before allowing exits.

Example: $10,000 position with 0.06% taker fee
- Entry fee: $6
- Exit fee: $6
- Round-trip: $12
- Breakeven: 12 bps (0.12%)

A trade that shows +10 bps gross profit is actually -2 bps net after fees!
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FeeConfig:
    """Fee configuration for an exchange/tier.
    
    All rates are expressed as decimals (e.g., 0.0006 = 0.06% = 6 bps).
    """
    taker_fee_rate: float = 0.0006  # 0.06% default (6 bps) - conservative
    maker_fee_rate: float = 0.0004  # 0.04% default (4 bps)
    maker_rebate_rate: float = 0.0  # No rebate by default
    
    @classmethod
    def okx_regular(cls) -> "FeeConfig":
        """OKX regular account fees."""
        return cls(taker_fee_rate=0.0006, maker_fee_rate=0.0004, maker_rebate_rate=0.0)
    
    @classmethod
    def okx_vip1(cls) -> "FeeConfig":
        """OKX VIP-1 account fees with maker rebate."""
        return cls(taker_fee_rate=0.0004, maker_fee_rate=0.0002, maker_rebate_rate=0.0001)
    
    @classmethod
    def okx_vip2(cls) -> "FeeConfig":
        """OKX VIP-2 account fees."""
        return cls(taker_fee_rate=0.00035, maker_fee_rate=0.00015, maker_rebate_rate=0.00015)
    
    @classmethod
    def bybit_regular(cls) -> "FeeConfig":
        """Bybit regular account fees."""
        return cls(taker_fee_rate=0.00055, maker_fee_rate=0.0002, maker_rebate_rate=0.0)
    
    @classmethod
    def bybit_vip1(cls) -> "FeeConfig":
        """Bybit VIP-1 account fees."""
        return cls(taker_fee_rate=0.0004, maker_fee_rate=0.00015, maker_rebate_rate=0.0)
    
    @classmethod
    def bybit_spot(cls) -> "FeeConfig":
        """Bybit spot regular fees."""
        return cls(taker_fee_rate=0.001, maker_fee_rate=0.001, maker_rebate_rate=0.0)
    
    @classmethod
    def okx_spot(cls) -> "FeeConfig":
        """OKX spot regular fees."""
        return cls(taker_fee_rate=0.001, maker_fee_rate=0.0008, maker_rebate_rate=0.0)
    
    @classmethod
    def binance_spot(cls) -> "FeeConfig":
        """Binance spot regular fees."""
        return cls(taker_fee_rate=0.001, maker_fee_rate=0.001, maker_rebate_rate=0.0)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "taker_fee_rate": self.taker_fee_rate,
            "maker_fee_rate": self.maker_fee_rate,
            "maker_rebate_rate": self.maker_rebate_rate,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "FeeConfig":
        """Deserialize from dictionary."""
        return cls(
            taker_fee_rate=float(data.get("taker_fee_rate", 0.0006)),
            maker_fee_rate=float(data.get("maker_fee_rate", 0.0004)),
            maker_rebate_rate=float(data.get("maker_rebate_rate", 0.0)),
        )


@dataclass(frozen=True)
class BreakevenResult:
    """Result of breakeven calculation."""
    breakeven_price: float  # Price needed to break even
    breakeven_bps: float    # Breakeven as basis points from entry
    round_trip_fee_usd: float  # Total fees in USD
    entry_fee_usd: float
    exit_fee_usd: float
    side: str  # "long" or "short"
    entry_price: float
    size: float
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "breakeven_price": self.breakeven_price,
            "breakeven_bps": self.breakeven_bps,
            "round_trip_fee_usd": self.round_trip_fee_usd,
            "entry_fee_usd": self.entry_fee_usd,
            "exit_fee_usd": self.exit_fee_usd,
            "side": self.side,
            "entry_price": self.entry_price,
            "size": self.size,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "BreakevenResult":
        """Deserialize from dictionary."""
        return cls(
            breakeven_price=float(data["breakeven_price"]),
            breakeven_bps=float(data["breakeven_bps"]),
            round_trip_fee_usd=float(data["round_trip_fee_usd"]),
            entry_fee_usd=float(data["entry_fee_usd"]),
            exit_fee_usd=float(data["exit_fee_usd"]),
            side=str(data["side"]),
            entry_price=float(data["entry_price"]),
            size=float(data["size"]),
        )


@dataclass(frozen=True)
class FeeAwareExitCheck:
    """Result of fee-aware exit evaluation."""
    should_allow_exit: bool
    gross_pnl_bps: float
    net_pnl_bps: float
    breakeven_bps: float
    min_required_bps: float  # breakeven + buffer
    shortfall_bps: float     # How far below minimum (0 if above)
    reason: str
    
    # Additional context
    gross_pnl_usd: Optional[float] = None
    net_pnl_usd: Optional[float] = None
    estimated_exit_fee_usd: Optional[float] = None


class FeeModel:
    """Calculate trading fees and breakeven thresholds.
    
    This is the core component for fee-aware exit logic. It calculates:
    - Entry/exit fees based on order type (maker/taker)
    - Round-trip fees for complete trades
    - Breakeven thresholds (minimum profit to cover fees)
    - Exit profitability checks
    """
    
    def __init__(self, config: Optional[FeeConfig] = None):
        """Initialize with fee configuration.
        
        Args:
            config: Fee configuration. Defaults to conservative OKX regular rates.
        """
        self.config = config or FeeConfig.okx_regular()
    
    def calculate_entry_fee(
        self,
        size: float,
        price: float,
        is_maker: bool = False,
    ) -> float:
        """Calculate fee for entry order.
        
        Args:
            size: Position size in base currency (e.g., BTC)
            price: Entry price
            is_maker: True if limit order (maker), False if market order (taker)
            
        Returns:
            Fee amount in quote currency (e.g., USD)
        """
        if size <= 0 or price <= 0:
            return 0.0
        
        notional = size * price
        
        if is_maker:
            # Maker fee minus rebate (rebate reduces cost)
            effective_rate = max(0.0, self.config.maker_fee_rate - self.config.maker_rebate_rate)
            return notional * effective_rate
        else:
            return notional * self.config.taker_fee_rate
    
    def calculate_exit_fee(
        self,
        size: float,
        price: float,
        is_maker: bool = False,
    ) -> float:
        """Calculate fee for exit order.
        
        Args:
            size: Position size in base currency
            price: Exit price
            is_maker: True if limit order (maker), False if market order (taker)
            
        Returns:
            Fee amount in quote currency
        """
        # Exit fee calculation is identical to entry
        return self.calculate_entry_fee(size, price, is_maker)
    
    def calculate_round_trip_fee(
        self,
        size: float,
        entry_price: float,
        exit_price: float,
        entry_is_maker: bool = False,
        exit_is_maker: bool = False,
    ) -> float:
        """Calculate total round-trip fees (entry + exit).
        
        Args:
            size: Position size in base currency
            entry_price: Entry price
            exit_price: Exit price
            entry_is_maker: True if entry was maker order
            exit_is_maker: True if exit will be maker order
            
        Returns:
            Total fees in quote currency
        """
        entry_fee = self.calculate_entry_fee(size, entry_price, entry_is_maker)
        exit_fee = self.calculate_exit_fee(size, exit_price, exit_is_maker)
        return entry_fee + exit_fee
    
    def calculate_breakeven(
        self,
        size: float,
        entry_price: float,
        side: str,
        entry_is_maker: bool = False,
        exit_is_maker: bool = False,
    ) -> Optional[BreakevenResult]:
        """Calculate breakeven price and threshold.
        
        Args:
            size: Position size in base currency
            entry_price: Entry price
            side: "long" or "short"
            entry_is_maker: True if entry was maker order
            exit_is_maker: True if exit will be maker order
            
        Returns:
            BreakevenResult with breakeven price and bps, or None if invalid inputs
        """
        if size <= 0 or entry_price <= 0:
            return None
        
        side_normalized = side.lower()
        if side_normalized not in ("long", "short"):
            return None
        
        # Calculate fees at entry price (conservative estimate)
        entry_fee = self.calculate_entry_fee(size, entry_price, entry_is_maker)
        exit_fee = self.calculate_exit_fee(size, entry_price, exit_is_maker)
        round_trip_fee = entry_fee + exit_fee
        
        # Calculate breakeven price movement
        price_movement = round_trip_fee / size
        
        if side_normalized == "long":
            # Long: need price to rise to cover fees
            breakeven_price = entry_price + price_movement
        else:
            # Short: need price to fall to cover fees
            breakeven_price = entry_price - price_movement
        
        # Calculate breakeven in basis points
        notional = size * entry_price
        breakeven_bps = (round_trip_fee / notional) * 10000.0 if notional > 0 else 0.0
        
        return BreakevenResult(
            breakeven_price=breakeven_price,
            breakeven_bps=breakeven_bps,
            round_trip_fee_usd=round_trip_fee,
            entry_fee_usd=entry_fee,
            exit_fee_usd=exit_fee,
            side=side_normalized,
            entry_price=entry_price,
            size=size,
        )
    
    def check_exit_profitability(
        self,
        size: float,
        entry_price: float,
        current_price: float,
        side: str,
        min_profit_buffer_bps: float = 5.0,
        entry_is_maker: bool = False,
        exit_is_maker: bool = False,
        entry_fee_already_paid: Optional[float] = None,
    ) -> FeeAwareExitCheck:
        """Check if exit would be profitable after fees.
        
        This is the main method for fee-aware exit decisions.
        
        Args:
            size: Position size in base currency
            entry_price: Entry price
            current_price: Current/exit price
            side: "long" or "short"
            min_profit_buffer_bps: Minimum profit above breakeven required (default 5 bps)
            entry_is_maker: True if entry was maker order
            exit_is_maker: True if exit will be maker order
            entry_fee_already_paid: If known, the actual entry fee paid
            
        Returns:
            FeeAwareExitCheck with decision and context
        """
        # Handle invalid inputs
        if size <= 0 or entry_price <= 0 or current_price <= 0:
            return FeeAwareExitCheck(
                should_allow_exit=False,
                gross_pnl_bps=0.0,
                net_pnl_bps=0.0,
                breakeven_bps=0.0,
                min_required_bps=0.0,
                shortfall_bps=0.0,
                reason="invalid_inputs",
            )
        
        side_normalized = side.lower()
        if side_normalized not in ("long", "short"):
            return FeeAwareExitCheck(
                should_allow_exit=False,
                gross_pnl_bps=0.0,
                net_pnl_bps=0.0,
                breakeven_bps=0.0,
                min_required_bps=0.0,
                shortfall_bps=0.0,
                reason="invalid_side",
            )
        
        # Calculate gross PnL
        notional = size * entry_price
        if side_normalized == "long":
            gross_pnl_usd = (current_price - entry_price) * size
        else:
            gross_pnl_usd = (entry_price - current_price) * size
        
        gross_pnl_bps = (gross_pnl_usd / notional) * 10000.0 if notional > 0 else 0.0
        
        # Calculate fees
        if entry_fee_already_paid is not None:
            entry_fee = entry_fee_already_paid
        else:
            entry_fee = self.calculate_entry_fee(size, entry_price, entry_is_maker)
        
        exit_fee = self.calculate_exit_fee(size, current_price, exit_is_maker)
        total_fees = entry_fee + exit_fee
        
        # Calculate net PnL
        net_pnl_usd = gross_pnl_usd - total_fees
        net_pnl_bps = (net_pnl_usd / notional) * 10000.0 if notional > 0 else 0.0
        
        # Calculate breakeven
        breakeven_bps = (total_fees / notional) * 10000.0 if notional > 0 else 0.0
        
        # Calculate minimum required (breakeven + buffer)
        # Clamp negative buffer to 0
        effective_buffer = max(0.0, min_profit_buffer_bps)
        min_required_bps = breakeven_bps + effective_buffer
        
        # Determine if exit should be allowed
        should_allow = gross_pnl_bps >= min_required_bps
        
        # Calculate shortfall (how far below minimum)
        shortfall_bps = max(0.0, min_required_bps - gross_pnl_bps)
        
        # Determine reason
        if should_allow:
            reason = "profit_exceeds_threshold"
        elif gross_pnl_bps >= breakeven_bps:
            reason = "profit_below_buffer"
        else:
            reason = "profit_below_breakeven"
        
        return FeeAwareExitCheck(
            should_allow_exit=should_allow,
            gross_pnl_bps=round(gross_pnl_bps, 2),
            net_pnl_bps=round(net_pnl_bps, 2),
            breakeven_bps=round(breakeven_bps, 2),
            min_required_bps=round(min_required_bps, 2),
            shortfall_bps=round(shortfall_bps, 2),
            reason=reason,
            gross_pnl_usd=round(gross_pnl_usd, 4),
            net_pnl_usd=round(net_pnl_usd, 4),
            estimated_exit_fee_usd=round(exit_fee, 4),
        )


# Convenience function for quick breakeven calculation
def calculate_breakeven_bps(
    taker_fee_rate: float = 0.0006,
    entry_is_maker: bool = False,
    exit_is_maker: bool = False,
    maker_fee_rate: float = 0.0004,
) -> float:
    """Calculate breakeven in basis points for given fee rates.
    
    This is a quick helper for estimating breakeven without creating a full FeeModel.
    
    Args:
        taker_fee_rate: Taker fee rate (default 0.06%)
        entry_is_maker: True if entry is maker
        exit_is_maker: True if exit is maker
        maker_fee_rate: Maker fee rate (default 0.04%)
        
    Returns:
        Breakeven in basis points
    """
    entry_rate = maker_fee_rate if entry_is_maker else taker_fee_rate
    exit_rate = maker_fee_rate if exit_is_maker else taker_fee_rate
    total_rate = entry_rate + exit_rate
    return total_rate * 10000.0  # Convert to bps
