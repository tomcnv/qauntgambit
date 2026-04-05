"""
Data Readiness Gate - Tiered protection for scalping on live market data.

Based on production playbook:
- Uses exchange-produced timestamps (cts for orderbook, T for trades)
- Tiered gates: Green (full speed) → Yellow (degrade) → Red (exits only) → Emergency
- Rate-limited resync with exponential backoff
- Meltdown guard to prevent reconnect/resync thrash
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple
from collections import deque

from quantgambit.observability.logger import log_info, log_warning


class ReadinessLevel(Enum):
    """Data readiness tier."""
    GREEN = "green"      # Full speed - all systems go
    YELLOW = "yellow"    # Degraded - reduce size, stricter confirms
    RED = "red"          # No new entries - exits only
    EMERGENCY = "emergency"  # Treat data as unreliable


@dataclass
class ReadinessThresholds:
    """Configurable thresholds for data readiness gates."""
    
    # Book lag thresholds (cts-based, in ms)
    book_lag_green_ms: int = 150
    book_lag_yellow_ms: int = 300
    book_lag_red_ms: int = 800
    
    # Trade lag thresholds (T-based, in ms)
    trade_lag_green_ms: int = 200
    trade_lag_yellow_ms: int = 400
    trade_lag_red_ms: int = 1000
    
    # Receive gap thresholds (detect frozen feeds)
    book_gap_green_ms: int = 250
    book_gap_yellow_ms: int = 500
    book_gap_red_ms: int = 1000
    
    trade_gap_green_ms: int = 2000
    trade_gap_yellow_ms: int = 5000
    trade_gap_red_ms: int = 10000
    
    # Resync rate limiting
    resync_cooldown_sec: float = 2.0  # Min time between resyncs per symbol
    resync_backoff_max_sec: float = 30.0  # Max backoff
    
    # Meltdown guard
    meltdown_resyncs_per_symbol: int = 5  # Max resyncs per symbol in window
    meltdown_resyncs_global: int = 15  # Max resyncs process-wide in window
    meltdown_window_sec: float = 60.0  # Window for counting resyncs
    meltdown_pause_sec: float = 120.0  # Pause duration after meltdown


@dataclass
class SymbolReadiness:
    """Per-symbol readiness state."""
    symbol: str
    
    # Latest timestamps
    last_book_cts_ms: Optional[int] = None  # Last orderbook cts from exchange
    last_book_recv_ms: float = 0.0  # When we received last book update
    last_trade_ts_ms: Optional[int] = None  # Last trade T from exchange
    last_trade_recv_ms: float = 0.0  # When we received last trade
    
    # Resync tracking
    last_resync_at: float = 0.0
    resync_backoff_sec: float = 2.0
    resync_history: deque = field(default_factory=lambda: deque(maxlen=100))
    
    # Current state
    level: ReadinessLevel = ReadinessLevel.RED  # Start conservative
    book_lag_ms: int = 999999
    trade_lag_ms: int = 999999
    book_gap_ms: int = 999999
    trade_gap_ms: int = 999999


class DataReadinessGate:
    """
    Manages data readiness for scalping decisions.
    
    Usage:
        gate = DataReadinessGate()
        
        # Update on each orderbook message
        gate.update_book(symbol, cts_ms=msg['cts'])
        
        # Update on each trade message
        gate.update_trade(symbol, trade_ts_ms=msg['T'])
        
        # Check before entering position
        level = gate.check(symbol)
        if level == ReadinessLevel.GREEN:
            # Full speed
        elif level == ReadinessLevel.YELLOW:
            # Reduce size, stricter confirms
        elif level == ReadinessLevel.RED:
            # Exits only
        else:
            # Emergency - reduce risk
        
        # Check if resync is allowed (rate-limited)
        if gate.should_resync(symbol):
            gate.record_resync(symbol)
            # Trigger REST snapshot fetch
    """
    
    def __init__(self, thresholds: Optional[ReadinessThresholds] = None):
        self.thresholds = thresholds or ReadinessThresholds()
        self._symbols: Dict[str, SymbolReadiness] = {}
        self._global_resync_history: deque = deque(maxlen=500)
        self._meltdown_until: float = 0.0
        self._last_log_at: Dict[str, float] = {}  # Rate limit logging
    
    def _get_symbol(self, symbol: str) -> SymbolReadiness:
        if symbol not in self._symbols:
            self._symbols[symbol] = SymbolReadiness(symbol=symbol)
        return self._symbols[symbol]
    
    def update_book(self, symbol: str, cts_ms: Optional[int] = None) -> None:
        """Update book timestamps. Call on every orderbook message."""
        state = self._get_symbol(symbol)
        now_ms = time.time() * 1000
        state.last_book_recv_ms = now_ms
        if cts_ms is not None:
            state.last_book_cts_ms = cts_ms
    
    def update_trade(self, symbol: str, trade_ts_ms: Optional[int] = None) -> None:
        """Update trade timestamps. Call on every trade message."""
        state = self._get_symbol(symbol)
        now_ms = time.time() * 1000
        state.last_trade_recv_ms = now_ms
        if trade_ts_ms is not None:
            # Keep max of trade timestamps (trades can batch)
            if state.last_trade_ts_ms is None or trade_ts_ms > state.last_trade_ts_ms:
                state.last_trade_ts_ms = trade_ts_ms
    
    def check(self, symbol: str) -> ReadinessLevel:
        """
        Check data readiness for a symbol.
        Returns the current readiness level.
        """
        state = self._get_symbol(symbol)
        t = self.thresholds
        now_ms = time.time() * 1000
        
        # Calculate lags
        if state.last_book_cts_ms is not None:
            state.book_lag_ms = int(now_ms - state.last_book_cts_ms)
        else:
            state.book_lag_ms = 999999
            
        if state.last_trade_ts_ms is not None:
            state.trade_lag_ms = int(now_ms - state.last_trade_ts_ms)
        else:
            state.trade_lag_ms = 999999
        
        # Calculate gaps (receive-time based)
        if state.last_book_recv_ms > 0:
            state.book_gap_ms = int(now_ms - state.last_book_recv_ms)
        else:
            state.book_gap_ms = 999999
            
        if state.last_trade_recv_ms > 0:
            state.trade_gap_ms = int(now_ms - state.last_trade_recv_ms)
        else:
            state.trade_gap_ms = 999999
        
        # Check meltdown state
        if time.time() < self._meltdown_until:
            state.level = ReadinessLevel.EMERGENCY
            return ReadinessLevel.EMERGENCY
        
        # Determine level based on worst condition
        level = ReadinessLevel.GREEN
        
        # Check book lag
        if state.book_lag_ms > t.book_lag_red_ms:
            level = ReadinessLevel.EMERGENCY
        elif state.book_lag_ms > t.book_lag_yellow_ms:
            level = max(level, ReadinessLevel.RED, key=lambda x: list(ReadinessLevel).index(x))
        elif state.book_lag_ms > t.book_lag_green_ms:
            level = max(level, ReadinessLevel.YELLOW, key=lambda x: list(ReadinessLevel).index(x))
        
        # Use receive-time gap if it is fresher than exchange-time lag to avoid
        # blocking on exchange timestamp skew/batching while feeds are live.
        effective_trade_lag_ms = state.trade_lag_ms
        if state.trade_gap_ms != 999999 and state.trade_gap_ms < effective_trade_lag_ms:
            effective_trade_lag_ms = state.trade_gap_ms

        # Check trade lag
        if effective_trade_lag_ms > t.trade_lag_red_ms:
            level = ReadinessLevel.EMERGENCY
        elif effective_trade_lag_ms > t.trade_lag_yellow_ms:
            level = max(level, ReadinessLevel.RED, key=lambda x: list(ReadinessLevel).index(x))
        elif effective_trade_lag_ms > t.trade_lag_green_ms:
            level = max(level, ReadinessLevel.YELLOW, key=lambda x: list(ReadinessLevel).index(x))
        
        # Check book gap (frozen feed detection)
        if state.book_gap_ms > t.book_gap_red_ms:
            level = ReadinessLevel.EMERGENCY
        elif state.book_gap_ms > t.book_gap_yellow_ms:
            level = max(level, ReadinessLevel.RED, key=lambda x: list(ReadinessLevel).index(x))
        elif state.book_gap_ms > t.book_gap_green_ms:
            level = max(level, ReadinessLevel.YELLOW, key=lambda x: list(ReadinessLevel).index(x))
        
        # Check trade gap
        if state.trade_gap_ms > t.trade_gap_red_ms:
            level = ReadinessLevel.EMERGENCY
        elif state.trade_gap_ms > t.trade_gap_yellow_ms:
            level = max(level, ReadinessLevel.RED, key=lambda x: list(ReadinessLevel).index(x))
        elif state.trade_gap_ms > t.trade_gap_green_ms:
            level = max(level, ReadinessLevel.YELLOW, key=lambda x: list(ReadinessLevel).index(x))
        
        # Log level changes
        old_level = state.level
        state.level = level
        if level != old_level:
            self._log_level_change(symbol, old_level, level, state)
        
        return level
    
    def _log_level_change(
        self, symbol: str, old: ReadinessLevel, new: ReadinessLevel, state: SymbolReadiness
    ) -> None:
        """Log readiness level changes (rate-limited)."""
        now = time.time()
        key = f"{symbol}:{new.value}"
        if now - self._last_log_at.get(key, 0) < 5.0:  # Max once per 5s per level
            return
        self._last_log_at[key] = now
        
        log_fn = log_warning if new in (ReadinessLevel.RED, ReadinessLevel.EMERGENCY) else log_info
        log_fn(
            "data_readiness_change",
            symbol=symbol,
            old_level=old.value,
            new_level=new.value,
            book_lag_ms=state.book_lag_ms,
            trade_lag_ms=state.trade_lag_ms,
            book_gap_ms=state.book_gap_ms,
            trade_gap_ms=state.trade_gap_ms,
        )
    
    def allows_entry(self, symbol: str) -> bool:
        """Check if new entries are allowed (GREEN or YELLOW only)."""
        level = self.check(symbol)
        return level in (ReadinessLevel.GREEN, ReadinessLevel.YELLOW)
    
    def get_size_multiplier(self, symbol: str) -> float:
        """
        Get position size multiplier based on readiness.
        GREEN = 1.0 (full size)
        YELLOW = 0.5 (half size)
        RED/EMERGENCY = 0.0 (no new entries)
        """
        level = self.check(symbol)
        if level == ReadinessLevel.GREEN:
            return 1.0
        elif level == ReadinessLevel.YELLOW:
            return 0.5
        return 0.0
    
    def should_resync(self, symbol: str) -> bool:
        """
        Check if a REST resync is allowed (respects rate limits).
        Returns True if resync is permitted.
        """
        state = self._get_symbol(symbol)
        now = time.time()
        
        # Check meltdown
        if now < self._meltdown_until:
            return False
        
        # Check cooldown with backoff
        if now - state.last_resync_at < state.resync_backoff_sec:
            return False
        
        return True
    
    def record_resync(self, symbol: str) -> None:
        """
        Record that a resync was triggered.
        Updates backoff and checks for meltdown.
        """
        state = self._get_symbol(symbol)
        now = time.time()
        t = self.thresholds
        
        # Record timestamps
        state.last_resync_at = now
        state.resync_history.append(now)
        self._global_resync_history.append((symbol, now))
        
        # Increase backoff (exponential)
        state.resync_backoff_sec = min(
            state.resync_backoff_sec * 2,
            t.resync_backoff_max_sec
        )
        
        log_info(
            "data_resync_triggered",
            symbol=symbol,
            backoff_sec=state.resync_backoff_sec,
        )
        
        # Check for meltdown
        self._check_meltdown(symbol)
    
    def _check_meltdown(self, symbol: str) -> None:
        """Check if we've hit meltdown thresholds."""
        state = self._get_symbol(symbol)
        t = self.thresholds
        now = time.time()
        window_start = now - t.meltdown_window_sec
        
        # Count recent resyncs for this symbol
        symbol_resyncs = sum(1 for ts in state.resync_history if ts > window_start)
        
        # Count global resyncs
        global_resyncs = sum(1 for _, ts in self._global_resync_history if ts > window_start)
        
        if symbol_resyncs >= t.meltdown_resyncs_per_symbol:
            log_warning(
                "data_meltdown_triggered",
                reason="symbol_resync_limit",
                symbol=symbol,
                resyncs=symbol_resyncs,
                threshold=t.meltdown_resyncs_per_symbol,
            )
            self._meltdown_until = now + t.meltdown_pause_sec
            
        elif global_resyncs >= t.meltdown_resyncs_global:
            log_warning(
                "data_meltdown_triggered",
                reason="global_resync_limit",
                resyncs=global_resyncs,
                threshold=t.meltdown_resyncs_global,
            )
            self._meltdown_until = now + t.meltdown_pause_sec
    
    def reset_backoff(self, symbol: str) -> None:
        """Reset backoff after successful period (call after stable data)."""
        state = self._get_symbol(symbol)
        state.resync_backoff_sec = self.thresholds.resync_cooldown_sec
    
    def get_status(self, symbol: str) -> dict:
        """Get detailed status for a symbol (for telemetry/debugging)."""
        state = self._get_symbol(symbol)
        return {
            "symbol": symbol,
            "level": state.level.value,
            "book_lag_ms": state.book_lag_ms,
            "trade_lag_ms": state.trade_lag_ms,
            "book_gap_ms": state.book_gap_ms,
            "trade_gap_ms": state.trade_gap_ms,
            "allows_entry": self.allows_entry(symbol),
            "size_multiplier": self.get_size_multiplier(symbol),
            "resync_backoff_sec": state.resync_backoff_sec,
            "in_meltdown": time.time() < self._meltdown_until,
        }
    
    def get_all_status(self) -> Dict[str, dict]:
        """Get status for all tracked symbols."""
        return {symbol: self.get_status(symbol) for symbol in self._symbols}


# Convenience function for quick check
def check_data_ready(
    book_lag_ms: int,
    trade_lag_ms: int,
    book_gap_ms: int = 0,
    trade_gap_ms: int = 0,
) -> Tuple[bool, ReadinessLevel]:
    """
    Quick check if data is ready for entries.
    
    Returns (allows_entry, level)
    
    Default thresholds (drop-in policy):
    - book_lag_ms ≤ 300
    - trade_lag_ms ≤ 400
    - book_gap_ms ≤ 250
    - trade_gap_ms ≤ 500
    """
    # Simple drop-in policy from playbook
    if (book_lag_ms <= 300 and trade_lag_ms <= 400 and 
        book_gap_ms <= 250 and trade_gap_ms <= 500):
        if book_lag_ms <= 150 and trade_lag_ms <= 200:
            return True, ReadinessLevel.GREEN
        return True, ReadinessLevel.YELLOW
    
    if book_lag_ms > 800 or trade_lag_ms > 1000:
        return False, ReadinessLevel.EMERGENCY
    
    return False, ReadinessLevel.RED
