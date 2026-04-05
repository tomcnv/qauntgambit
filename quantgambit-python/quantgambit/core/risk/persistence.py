"""
Kill switch persistence and account-level guards.

Provides:
- Durable kill switch state (survives restarts)
- Account-level guards (equity, margin, fee budgets)
- Per-symbol cooldowns
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, Optional, Protocol

from quantgambit.core.clock import Clock
from quantgambit.core.risk.kill_switch import KillSwitch, KillSwitchTrigger

logger = logging.getLogger(__name__)


class KillSwitchStore(Protocol):
    """Protocol for kill switch persistence."""
    
    async def save(self, state: Dict[str, Any]) -> None:
        """Save kill switch state."""
        ...
    
    async def load(self) -> Optional[Dict[str, Any]]:
        """Load kill switch state."""
        ...


class RedisKillSwitchStore:
    """Redis-based kill switch store."""
    
    def __init__(self, redis_client: Any, key: str = "quantgambit:kill_switch"):
        """Initialize store."""
        self._redis = redis_client
        self._key = key
    
    async def save(self, state: Dict[str, Any]) -> None:
        """Save kill switch state to Redis."""
        try:
            await self._redis.set(self._key, json.dumps(state))
            logger.debug(f"Saved kill switch state to Redis")
        except Exception as e:
            logger.error(f"Failed to save kill switch state: {e}")
    
    async def load(self) -> Optional[Dict[str, Any]]:
        """Load kill switch state from Redis."""
        try:
            data = await self._redis.get(self._key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to load kill switch state: {e}")
            return None


@dataclass
class AccountGuards:
    """
    Account-level trading guards.
    
    These guards protect the account from excessive losses
    and enforce position limits.
    """
    
    # Equity guards
    max_daily_loss_pct: float = 0.05  # 5% max daily loss
    max_drawdown_pct: float = 0.10  # 10% max drawdown from peak
    min_equity: float = 100.0  # Minimum equity to trade
    
    # Margin guards
    min_available_margin_pct: float = 0.20  # 20% min available
    max_margin_used_pct: float = 0.80  # 80% max margin used
    
    # Fee budget
    max_daily_fees: float = 100.0  # Max daily fees
    fee_warning_threshold_pct: float = 0.80  # Warn at 80%
    
    # Position guards
    max_position_value: float = 10000.0  # Max total position value
    max_positions: int = 5  # Max concurrent positions
    max_position_hold_s: float = 3600.0  # Max 1 hour hold
    
    # Per-symbol cooldown
    cooldown_after_stopout_s: float = 300.0  # 5 min cooldown after stop


@dataclass
class AccountState:
    """Current account state for guard checks."""
    
    equity: float = 0.0
    peak_equity: float = 0.0
    daily_start_equity: float = 0.0
    available_margin: float = 0.0
    total_margin_used: float = 0.0
    daily_fees: float = 0.0
    daily_pnl: float = 0.0
    position_count: int = 0
    total_position_value: float = 0.0
    
    # Tracking
    daily_reset_ts: float = 0.0
    
    def update_daily(self, ts: float, reset_hour: int = 0) -> None:
        """Reset daily counters if needed."""
        dt = datetime.fromtimestamp(ts)
        if dt.hour == reset_hour and ts - self.daily_reset_ts > 3600:
            self.daily_start_equity = self.equity
            self.daily_fees = 0.0
            self.daily_pnl = 0.0
            self.daily_reset_ts = ts
    
    def current_drawdown_pct(self) -> float:
        """Calculate current drawdown from peak."""
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity
    
    def current_daily_loss_pct(self) -> float:
        """Calculate current daily loss."""
        if self.daily_start_equity <= 0:
            return 0.0
        return (self.daily_start_equity - self.equity) / self.daily_start_equity


@dataclass
class SymbolCooldown:
    """Per-symbol cooldown state."""
    
    cooldowns: Dict[str, float] = field(default_factory=dict)  # symbol -> cooldown_until_ts
    
    def set_cooldown(self, symbol: str, until_ts: float) -> None:
        """Set cooldown for symbol."""
        self.cooldowns[symbol] = until_ts
    
    def is_cooled_down(self, symbol: str, current_ts: float) -> bool:
        """Check if symbol is in cooldown."""
        cooldown_until = self.cooldowns.get(symbol, 0.0)
        return current_ts < cooldown_until
    
    def clear_expired(self, current_ts: float) -> None:
        """Clear expired cooldowns."""
        self.cooldowns = {
            symbol: until for symbol, until in self.cooldowns.items()
            if until > current_ts
        }


class PersistentKillSwitch:
    """
    Kill switch with persistence and account guards.
    
    Wraps the base KillSwitch with:
    - Durable state storage
    - Account-level guards
    - Per-symbol cooldowns
    - Automatic recovery on restart
    """
    
    def __init__(
        self,
        kill_switch: KillSwitch,
        store: KillSwitchStore,
        clock: Clock,
        guards: Optional[AccountGuards] = None,
    ):
        """Initialize persistent kill switch."""
        self._kill_switch = kill_switch
        self._store = store
        self._clock = clock
        self._guards = guards or AccountGuards()
        
        self._account_state = AccountState()
        self._cooldowns = SymbolCooldown()
    
    async def initialize(self) -> None:
        """
        Load persisted state on startup.
        
        If kill switch was active, it stays active until explicitly reset.
        """
        state = await self._store.load()
        if state:
            if state.get("is_active", False):
                # Restore kill switch state
                for trigger_name, ts in state.get("triggered_by", {}).items():
                    try:
                        trigger = KillSwitchTrigger(trigger_name)
                        self._kill_switch.trigger(trigger, f"Restored from persistence (triggered at {ts})")
                    except ValueError:
                        pass
                logger.warning("Kill switch restored as ACTIVE from persistence")
            
            # Restore cooldowns
            cooldowns = state.get("cooldowns", {})
            for symbol, until_ts in cooldowns.items():
                self._cooldowns.set_cooldown(symbol, until_ts)
    
    async def save_state(self) -> None:
        """Save current state to store."""
        ks_state = self._kill_switch.get_state()
        state = {
            "is_active": ks_state.is_active,
            "triggered_by": {t.value: ts for t, ts in ks_state.triggered_by.items()},
            "message": ks_state.message,
            "last_reset_ts": ks_state.last_reset_ts,
            "cooldowns": self._cooldowns.cooldowns,
            "saved_at": self._clock.now(),
        }
        await self._store.save(state)
    
    def update_account_state(
        self,
        equity: float,
        available_margin: float,
        margin_used: float,
        position_count: int,
        position_value: float,
    ) -> None:
        """Update account state and check guards."""
        self._account_state.equity = equity
        self._account_state.available_margin = available_margin
        self._account_state.total_margin_used = margin_used
        self._account_state.position_count = position_count
        self._account_state.total_position_value = position_value
        
        # Update peak
        if equity > self._account_state.peak_equity:
            self._account_state.peak_equity = equity
        
        # Update daily
        self._account_state.update_daily(self._clock.now())
        
        # Check guards
        self._check_account_guards()
    
    def add_fee(self, amount: float) -> None:
        """Track fee payment."""
        self._account_state.daily_fees += amount
        self._check_fee_guard()
    
    def set_symbol_cooldown(self, symbol: str, reason: str = "") -> None:
        """Set cooldown for a symbol."""
        until_ts = self._clock.now() + self._guards.cooldown_after_stopout_s
        self._cooldowns.set_cooldown(symbol, until_ts)
        logger.info(f"Symbol {symbol} in cooldown until {until_ts} ({reason})")
    
    def can_trade(self, symbol: str) -> tuple[bool, str]:
        """
        Check if trading is allowed for symbol.
        
        Returns:
            (allowed, reason) tuple
        """
        # Kill switch check
        if self._kill_switch.is_active():
            return False, "Kill switch active"
        
        # Cooldown check
        if self._cooldowns.is_cooled_down(symbol, self._clock.now()):
            return False, f"Symbol {symbol} in cooldown"
        
        # Account guards
        if self._account_state.equity < self._guards.min_equity:
            return False, f"Equity below minimum ({self._guards.min_equity})"
        
        if self._account_state.position_count >= self._guards.max_positions:
            return False, f"Max positions reached ({self._guards.max_positions})"
        
        if self._account_state.total_position_value >= self._guards.max_position_value:
            return False, f"Max position value reached"
        
        return True, ""
    
    def _check_account_guards(self) -> None:
        """Check account-level guards and trigger kill switch if needed."""
        # Drawdown guard
        dd = self._account_state.current_drawdown_pct()
        if dd > self._guards.max_drawdown_pct:
            self._kill_switch.trigger(
                KillSwitchTrigger.EQUITY_DRAWDOWN,
                f"Drawdown {dd:.1%} exceeds max {self._guards.max_drawdown_pct:.1%}",
            )
        
        # Daily loss guard
        daily_loss = self._account_state.current_daily_loss_pct()
        if daily_loss > self._guards.max_daily_loss_pct:
            self._kill_switch.trigger(
                KillSwitchTrigger.EQUITY_DRAWDOWN,
                f"Daily loss {daily_loss:.1%} exceeds max {self._guards.max_daily_loss_pct:.1%}",
            )
        
        # Margin guard
        if self._account_state.equity > 0:
            margin_pct = self._account_state.total_margin_used / self._account_state.equity
            if margin_pct > self._guards.max_margin_used_pct:
                logger.warning(f"High margin usage: {margin_pct:.1%}")
    
    def _check_fee_guard(self) -> None:
        """Check fee budget."""
        if self._account_state.daily_fees >= self._guards.max_daily_fees:
            logger.warning(f"Daily fee budget exhausted: {self._account_state.daily_fees}")
        elif self._account_state.daily_fees >= self._guards.max_daily_fees * self._guards.fee_warning_threshold_pct:
            logger.warning(f"Daily fees at warning threshold: {self._account_state.daily_fees}")
    
    def is_active(self) -> bool:
        """Check if kill switch is active."""
        return self._kill_switch.is_active()
    
    async def reset(self, operator_id: str) -> None:
        """Reset kill switch (requires explicit operator action)."""
        self._kill_switch.reset(operator_id)
        await self.save_state()
        logger.warning(f"Kill switch reset by {operator_id}")
