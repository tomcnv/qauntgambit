"""
Position Manager - Manage open positions

Manages:
1. Position tracking (entry, size, P&L)
2. Stop loss management (fixed, trailing)
3. Take profit management (fixed, partial)
4. Position updates (mark-to-market)
5. Position closing

Returns position status and actions.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
import time


class PositionSide(Enum):
    """Position side"""
    LONG = "long"
    SHORT = "short"


class PositionStatus(Enum):
    """Position status"""
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class Position:
    """Trading position"""
    position_id: str
    symbol: str
    side: PositionSide
    entry_price: float
    size_units: float
    size_usd: float
    stop_loss: float
    take_profit: float
    entry_time: float
    
    # Current state
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    
    # Trailing stop
    trailing_stop_enabled: bool = False
    trailing_stop_distance_bps: float = 50.0  # 50 bps trailing distance
    highest_price: float = 0.0  # For long positions
    lowest_price: float = 0.0  # For short positions
    
    # Metadata
    profile_id: Optional[str] = None
    strategy_id: Optional[str] = None
    signal_id: Optional[str] = None
    notes: str = ""
    
    def __post_init__(self):
        """Initialize derived fields"""
        if self.current_price == 0.0:
            self.current_price = self.entry_price
        if self.highest_price == 0.0:
            self.highest_price = self.entry_price
        if self.lowest_price == 0.0:
            self.lowest_price = self.entry_price
    
    def update_price(self, new_price: float):
        """Update current price and calculate P&L"""
        self.current_price = new_price
        
        # Update highest/lowest for trailing stop
        if self.side == PositionSide.LONG:
            self.highest_price = max(self.highest_price, new_price)
        else:
            self.lowest_price = min(self.lowest_price, new_price)
        
        # Calculate unrealized P&L
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (new_price - self.entry_price) * self.size_units
            self.unrealized_pnl_pct = (new_price - self.entry_price) / self.entry_price * 100
        else:  # SHORT
            self.unrealized_pnl = (self.entry_price - new_price) * self.size_units
            self.unrealized_pnl_pct = (self.entry_price - new_price) / self.entry_price * 100
    
    def should_stop_loss(self) -> bool:
        """Check if stop loss should be triggered"""
        if self.side == PositionSide.LONG:
            return self.current_price <= self.stop_loss
        else:  # SHORT
            return self.current_price >= self.stop_loss
    
    def should_take_profit(self) -> bool:
        """Check if take profit should be triggered"""
        if self.side == PositionSide.LONG:
            return self.current_price >= self.take_profit
        else:  # SHORT
            return self.current_price <= self.take_profit
    
    def update_trailing_stop(self):
        """Update trailing stop loss"""
        if not self.trailing_stop_enabled:
            return
        
        if self.side == PositionSide.LONG:
            # Trail stop up as price rises
            trailing_stop = self.highest_price * (1 - self.trailing_stop_distance_bps / 10000)
            self.stop_loss = max(self.stop_loss, trailing_stop)
        else:  # SHORT
            # Trail stop down as price falls
            trailing_stop = self.lowest_price * (1 + self.trailing_stop_distance_bps / 10000)
            self.stop_loss = min(self.stop_loss, trailing_stop)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'position_id': self.position_id,
            'symbol': self.symbol,
            'side': self.side.value,
            'entry_price': self.entry_price,
            'size_units': self.size_units,
            'size_usd': self.size_usd,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'entry_time': self.entry_time,
            'current_price': self.current_price,
            'unrealized_pnl': self.unrealized_pnl,
            'unrealized_pnl_pct': self.unrealized_pnl_pct,
            'status': self.status.value,
            'trailing_stop_enabled': self.trailing_stop_enabled,
            'profile_id': self.profile_id,
            'strategy_id': self.strategy_id,
            'signal_id': self.signal_id,
        }


class PositionManager:
    """Manage open positions"""
    
    def __init__(self):
        self.positions: Dict[str, Position] = {}  # position_id -> Position
        self.closed_positions: List[Position] = []
        
        # Stats
        self.total_positions_opened = 0
        self.total_positions_closed = 0
        self.total_realized_pnl = 0.0
    
    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size_units: float,
        size_usd: float,
        stop_loss: float,
        take_profit: float,
        profile_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        signal_id: Optional[str] = None
    ) -> Position:
        """
        Open a new position
        
        Args:
            symbol: Trading symbol
            side: Position side ('long' or 'short')
            entry_price: Entry price
            size_units: Position size in units
            size_usd: Position size in USD
            stop_loss: Stop loss price
            take_profit: Take profit price
            profile_id: Profile ID (optional)
            strategy_id: Strategy ID (optional)
            signal_id: Signal ID (optional)
            
        Returns:
            Position object
        """
        position_id = f"{symbol}_{side}_{int(time.time() * 1000)}"
        
        position = Position(
            position_id=position_id,
            symbol=symbol,
            side=PositionSide.LONG if side == "long" else PositionSide.SHORT,
            entry_price=entry_price,
            size_units=size_units,
            size_usd=size_usd,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=time.time(),
            profile_id=profile_id,
            strategy_id=strategy_id,
            signal_id=signal_id,
        )
        
        self.positions[position_id] = position
        self.total_positions_opened += 1
        
        return position
    
    def close_position(
        self,
        position_id: str,
        exit_price: float,
        reason: str = "manual"
    ) -> Optional[Dict]:
        """
        Close a position
        
        Args:
            position_id: Position ID
            exit_price: Exit price
            reason: Close reason
            
        Returns:
            Dict with position info and realized P&L
        """
        if position_id not in self.positions:
            return None
        
        position = self.positions[position_id]
        position.update_price(exit_price)
        position.status = PositionStatus.CLOSED
        
        # Calculate realized P&L
        realized_pnl = position.unrealized_pnl
        realized_pnl_pct = position.unrealized_pnl_pct
        
        # Move to closed positions
        self.closed_positions.append(position)
        del self.positions[position_id]
        
        # Update stats
        self.total_positions_closed += 1
        self.total_realized_pnl += realized_pnl
        
        return {
            'position_id': position_id,
            'symbol': position.symbol,
            'side': position.side.value,
            'entry_price': position.entry_price,
            'exit_price': exit_price,
            'size_units': position.size_units,
            'size_usd': position.size_usd,
            'realized_pnl': realized_pnl,
            'realized_pnl_pct': realized_pnl_pct,
            'hold_time_sec': time.time() - position.entry_time,
            'close_reason': reason,
        }
    
    def update_positions(self, prices: Dict[str, float]) -> List[Dict]:
        """
        Update all positions with current prices
        
        Args:
            prices: Dict of symbol -> current_price
            
        Returns:
            List of actions (stop_loss, take_profit, trailing_stop_update)
        """
        actions = []
        
        for position_id, position in list(self.positions.items()):
            if position.symbol not in prices:
                continue
            
            current_price = prices[position.symbol]
            position.update_price(current_price)
            
            # Check stop loss
            if position.should_stop_loss():
                actions.append({
                    'action': 'stop_loss',
                    'position_id': position_id,
                    'symbol': position.symbol,
                    'current_price': current_price,
                    'stop_loss': position.stop_loss,
                })
            
            # Check take profit
            elif position.should_take_profit():
                actions.append({
                    'action': 'take_profit',
                    'position_id': position_id,
                    'symbol': position.symbol,
                    'current_price': current_price,
                    'take_profit': position.take_profit,
                })
            
            # Update trailing stop
            if position.trailing_stop_enabled:
                old_stop = position.stop_loss
                position.update_trailing_stop()
                if position.stop_loss != old_stop:
                    actions.append({
                        'action': 'trailing_stop_update',
                        'position_id': position_id,
                        'symbol': position.symbol,
                        'old_stop': old_stop,
                        'new_stop': position.stop_loss,
                    })
        
        return actions
    
    def get_position(self, position_id: str) -> Optional[Position]:
        """Get a position by ID"""
        return self.positions.get(position_id)
    
    def get_positions_by_symbol(self, symbol: str) -> List[Position]:
        """Get all positions for a symbol"""
        return [p for p in self.positions.values() if p.symbol == symbol]
    
    def get_all_positions(self) -> List[Position]:
        """Get all open positions"""
        return list(self.positions.values())
    
    def get_total_exposure_usd(self) -> float:
        """Get total exposure in USD"""
        return sum(p.size_usd for p in self.positions.values())
    
    def get_total_unrealized_pnl(self) -> float:
        """Get total unrealized P&L"""
        return sum(p.unrealized_pnl for p in self.positions.values())
    
    def get_stats(self) -> Dict:
        """Get position manager statistics"""
        open_positions = len(self.positions)
        total_exposure_usd = self.get_total_exposure_usd()
        total_unrealized_pnl = self.get_total_unrealized_pnl()
        
        avg_realized_pnl = self.total_realized_pnl / self.total_positions_closed if self.total_positions_closed > 0 else 0.0
        
        return {
            'open_positions': open_positions,
            'total_positions_opened': self.total_positions_opened,
            'total_positions_closed': self.total_positions_closed,
            'total_exposure_usd': total_exposure_usd,
            'total_unrealized_pnl': total_unrealized_pnl,
            'total_realized_pnl': self.total_realized_pnl,
            'avg_realized_pnl': avg_realized_pnl,
        }























