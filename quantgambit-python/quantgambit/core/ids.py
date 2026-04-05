"""
ID generation for intents and orders.

Two-level identity scheme:
1. intent_id: Stable hash of trading decision parameters (idempotency key)
2. client_order_id: Venue-facing ID derived from intent_id + attempt counter

This enables:
- Idempotent order submission (same intent = same intent_id)
- Retry tracking (new attempt = new client_order_id)
- Correlation across the order lifecycle
- Venue-compliant ID formats (length limits, character restrictions)

Scheme:
- intent_id = "i_" + sha256(strategy_id|symbol|side|qty|entry_type|entry_price|sl|tp|risk_mode|decision_bucket_ms)[:16]
- client_order_id = "qg_" + intent_id + "_a" + attempt

Example:
- intent_id: "i_a1b2c3d4e5f67890"
- client_order_id (attempt 1): "qg_i_a1b2c3d4e5f67890_a1"
- client_order_id (attempt 2): "qg_i_a1b2c3d4e5f67890_a2"
"""

from dataclasses import dataclass
from typing import Optional
import hashlib
import uuid


# Prefix for intent IDs
INTENT_PREFIX = "i_"

# Prefix for client order IDs (identifies QuantGambit orders)
CLIENT_ORDER_PREFIX = "qg_"

# Hash length for intent ID (16 hex chars = 64 bits)
INTENT_HASH_LENGTH = 16

# Maximum client order ID length (most venues allow 32-36 chars)
MAX_CLIENT_ORDER_ID_LENGTH = 32


@dataclass(frozen=True)
class IntentIdentity:
    """
    Two-level identity for an execution intent.
    
    Attributes:
        intent_id: Stable hash identifying the trading decision
        attempt: Attempt counter (starts at 1)
        client_order_id: Venue-facing order ID
    """
    
    intent_id: str
    attempt: int
    client_order_id: str
    
    @classmethod
    def create(
        cls,
        strategy_id: str,
        symbol: str,
        side: str,
        qty: float,
        entry_type: str,
        entry_price: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
        risk_mode: str,
        decision_ts_bucket: int,
        attempt: int = 1,
    ) -> "IntentIdentity":
        """
        Create an intent identity from decision parameters.
        
        Args:
            strategy_id: Strategy that generated the decision
            symbol: Trading symbol (e.g., "BTCUSDT")
            side: Order side ("buy" or "sell")
            qty: Order quantity
            entry_type: Order type ("market", "limit", etc.)
            entry_price: Limit price (None for market orders)
            stop_loss: Stop loss price (None if not set)
            take_profit: Take profit price (None if not set)
            risk_mode: Risk mode identifier
            decision_ts_bucket: Decision timestamp bucket (ms, rounded)
            attempt: Attempt counter (default 1)
            
        Returns:
            IntentIdentity with generated IDs
        """
        intent_id = generate_intent_id(
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            qty=qty,
            entry_type=entry_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_mode=risk_mode,
            decision_ts_bucket=decision_ts_bucket,
        )
        
        client_order_id = generate_client_order_id(intent_id, attempt)
        
        return cls(
            intent_id=intent_id,
            attempt=attempt,
            client_order_id=client_order_id,
        )
    
    def next_attempt(self) -> "IntentIdentity":
        """
        Create identity for next retry attempt.
        
        Returns:
            New IntentIdentity with incremented attempt
        """
        new_attempt = self.attempt + 1
        return IntentIdentity(
            intent_id=self.intent_id,
            attempt=new_attempt,
            client_order_id=generate_client_order_id(self.intent_id, new_attempt),
        )
    
    def is_same_intent(self, other: "IntentIdentity") -> bool:
        """Check if two identities represent the same intent (ignoring attempt)."""
        return self.intent_id == other.intent_id


def generate_trace_id() -> str:
    """
    Generate a unique trace ID for correlating events across the pipeline.
    
    Returns:
        A unique trace ID string (e.g., "tr_a1b2c3d4e5f67890")
    """
    return f"tr_{uuid.uuid4().hex[:16]}"


def generate_intent_id(
    strategy_id: str,
    symbol: str,
    side: str,
    qty: float,
    entry_type: str,
    entry_price: Optional[float],
    stop_loss: Optional[float],
    take_profit: Optional[float],
    risk_mode: str,
    decision_ts_bucket: int,
) -> str:
    """
    Generate a stable intent ID from decision parameters.
    
    The intent ID is a deterministic hash that uniquely identifies
    a trading decision. The same parameters always produce the same ID.
    
    Args:
        strategy_id: Strategy identifier
        symbol: Trading symbol
        side: Order side
        qty: Order quantity
        entry_type: Order type
        entry_price: Limit price (or None)
        stop_loss: Stop loss price (or None)
        take_profit: Take profit price (or None)
        risk_mode: Risk mode
        decision_ts_bucket: Timestamp bucket (for deduplication window)
        
    Returns:
        Intent ID string (e.g., "i_a1b2c3d4e5f67890")
    """
    # Normalize values for consistent hashing
    normalized_price = f"{entry_price:.8f}" if entry_price is not None else "none"
    normalized_sl = f"{stop_loss:.8f}" if stop_loss is not None else "none"
    normalized_tp = f"{take_profit:.8f}" if take_profit is not None else "none"
    normalized_qty = f"{qty:.8f}"
    
    # Build the hash input string
    hash_input = (
        f"{strategy_id}|{symbol}|{side}|{normalized_qty}|{entry_type}|"
        f"{normalized_price}|{normalized_sl}|{normalized_tp}|"
        f"{risk_mode}|{decision_ts_bucket}"
    )
    
    # Generate SHA256 hash and take first INTENT_HASH_LENGTH hex chars
    hash_bytes = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    hash_short = hash_bytes[:INTENT_HASH_LENGTH]
    
    return f"{INTENT_PREFIX}{hash_short}"


def generate_client_order_id(intent_id: str, attempt: int) -> str:
    """
    Generate a client order ID from intent ID and attempt number.
    
    The client order ID is what gets sent to the exchange. It must:
    - Be unique per order attempt
    - Be traceable back to the intent
    - Meet venue length/character requirements
    
    Args:
        intent_id: The intent ID (e.g., "i_a1b2c3d4e5f67890")
        attempt: Attempt number (1, 2, 3, ...)
        
    Returns:
        Client order ID string (e.g., "qg_i_a1b2c3d4e5f67890_a1")
        
    Raises:
        ValueError: If resulting ID exceeds MAX_CLIENT_ORDER_ID_LENGTH
    """
    client_order_id = f"{CLIENT_ORDER_PREFIX}{intent_id}_a{attempt}"
    
    if len(client_order_id) > MAX_CLIENT_ORDER_ID_LENGTH:
        # Truncate intent_id hash to fit within limit
        # Keep prefix, attempt suffix, and as much hash as possible
        prefix_len = len(CLIENT_ORDER_PREFIX) + len(INTENT_PREFIX)
        suffix_len = len(f"_a{attempt}")
        available_hash = MAX_CLIENT_ORDER_ID_LENGTH - prefix_len - suffix_len
        
        # Extract just the hash part from intent_id
        hash_part = intent_id[len(INTENT_PREFIX):]
        truncated_hash = hash_part[:available_hash]
        
        client_order_id = f"{CLIENT_ORDER_PREFIX}{INTENT_PREFIX}{truncated_hash}_a{attempt}"
    
    return client_order_id


def parse_client_order_id(client_order_id: str) -> Optional[tuple[str, int]]:
    """
    Parse a client order ID back into intent_id and attempt.
    
    Args:
        client_order_id: The client order ID to parse
        
    Returns:
        Tuple of (intent_id, attempt) or None if not a valid QuantGambit ID
    """
    if not client_order_id.startswith(CLIENT_ORDER_PREFIX):
        return None
    
    try:
        # Remove prefix
        remainder = client_order_id[len(CLIENT_ORDER_PREFIX):]
        
        # Split on "_a" to get intent_id and attempt
        if "_a" not in remainder:
            return None
        
        # Find the last "_a" (in case intent_id somehow contains "_a")
        last_a_idx = remainder.rfind("_a")
        intent_id = remainder[:last_a_idx]
        attempt_str = remainder[last_a_idx + 2:]
        
        attempt = int(attempt_str)
        return (intent_id, attempt)
        
    except (ValueError, IndexError):
        return None


def is_quantgambit_order(client_order_id: str) -> bool:
    """
    Check if a client order ID was generated by QuantGambit.
    
    Args:
        client_order_id: The client order ID to check
        
    Returns:
        True if this is a QuantGambit-generated order ID
    """
    return client_order_id.startswith(CLIENT_ORDER_PREFIX)


def bucket_timestamp(ts_ms: int, bucket_size_ms: int = 1000) -> int:
    """
    Bucket a timestamp for deduplication.
    
    Decisions within the same bucket are considered potentially duplicate.
    This prevents rapid-fire duplicate orders while allowing legitimate
    re-entries after the bucket window.
    
    Args:
        ts_ms: Timestamp in milliseconds
        bucket_size_ms: Bucket size in milliseconds (default 1000ms = 1s)
        
    Returns:
        Bucketed timestamp (start of bucket)
    """
    return (ts_ms // bucket_size_ms) * bucket_size_ms


@dataclass
class AttemptTracker:
    """
    Track attempt counts per intent for retry management.
    
    This should be persisted to survive restarts.
    """
    
    _attempts: dict[str, int]
    _max_attempts: int
    
    def __init__(self, max_attempts: int = 5):
        """
        Initialize tracker.
        
        Args:
            max_attempts: Maximum retry attempts per intent
        """
        self._attempts = {}
        self._max_attempts = max_attempts
    
    def get_attempt(self, intent_id: str) -> int:
        """Get current attempt number for an intent (0 if not seen)."""
        return self._attempts.get(intent_id, 0)
    
    def next_attempt(self, intent_id: str) -> Optional[int]:
        """
        Get next attempt number for an intent.
        
        Args:
            intent_id: The intent ID
            
        Returns:
            Next attempt number, or None if max attempts exceeded
        """
        current = self._attempts.get(intent_id, 0)
        next_num = current + 1
        
        if next_num > self._max_attempts:
            return None
        
        self._attempts[intent_id] = next_num
        return next_num
    
    def reset(self, intent_id: str) -> None:
        """Reset attempt counter for an intent (e.g., after success)."""
        self._attempts.pop(intent_id, None)
    
    def clear_old(self, intent_ids_to_keep: set[str]) -> int:
        """
        Clear attempt counters for intents not in the keep set.
        
        Args:
            intent_ids_to_keep: Set of intent IDs to retain
            
        Returns:
            Number of entries cleared
        """
        to_remove = [k for k in self._attempts if k not in intent_ids_to_keep]
        for k in to_remove:
            del self._attempts[k]
        return len(to_remove)
    
    def to_dict(self) -> dict[str, int]:
        """Serialize for persistence."""
        return dict(self._attempts)
    
    @classmethod
    def from_dict(cls, data: dict[str, int], max_attempts: int = 5) -> "AttemptTracker":
        """Deserialize from persistence."""
        tracker = cls(max_attempts=max_attempts)
        tracker._attempts = dict(data)
        return tracker
