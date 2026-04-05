"""
Redis-backed kill switch state persistence.

Ensures kill switch state survives restarts and is shared across instances.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

from quantgambit.core.risk.kill_switch import KillSwitchTrigger

logger = logging.getLogger(__name__)


@dataclass
class KillSwitchState:
    """Persistent kill switch state."""
    
    is_active: bool = False
    triggered_by: Dict[str, float] = field(default_factory=dict)  # trigger_name -> timestamp
    message: str = ""
    last_reset_ts: float = 0.0
    last_reset_by: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KillSwitchState":
        return cls(
            is_active=data.get("is_active", False),
            triggered_by=data.get("triggered_by", {}),
            message=data.get("message", ""),
            last_reset_ts=data.get("last_reset_ts", 0.0),
            last_reset_by=data.get("last_reset_by", ""),
        )


class RedisKillSwitchStore:
    """
    Redis-backed persistence for kill switch state.
    
    Storage scheme:
    - quantgambit:{tenant_id}:{bot_id}:kill_switch:state -> state JSON
    - quantgambit:{tenant_id}:{bot_id}:kill_switch:history -> list of trigger/reset events
    """
    
    def __init__(self, redis_client, tenant_id: str, bot_id: str):
        """
        Initialize Redis kill switch store.
        
        Args:
            redis_client: Async Redis client
            tenant_id: Tenant identifier
            bot_id: Bot identifier
        """
        self._redis = redis_client
        self._tenant_id = tenant_id
        self._bot_id = bot_id
        self._prefix = f"quantgambit:{tenant_id}:{bot_id}:kill_switch"
    
    def _state_key(self) -> str:
        return f"{self._prefix}:state"
    
    def _history_key(self) -> str:
        return f"{self._prefix}:history"
    
    async def load_state(self) -> KillSwitchState:
        """Load kill switch state from Redis."""
        key = self._state_key()
        data = await self._redis.get(key)
        
        if not data:
            return KillSwitchState()
        
        try:
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            state_dict = json.loads(data)
            return KillSwitchState.from_dict(state_dict)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load kill switch state: {e}")
            return KillSwitchState()
    
    async def save_state(self, state: KillSwitchState) -> None:
        """Save kill switch state to Redis."""
        key = self._state_key()
        data = json.dumps(state.to_dict())
        await self._redis.set(key, data)
        logger.debug(f"Saved kill switch state: is_active={state.is_active}")
    
    async def record_trigger(
        self,
        trigger: str,
        message: str,
        timestamp: float,
    ) -> None:
        """Record a kill switch trigger event."""
        event = {
            "type": "trigger",
            "trigger": trigger,
            "message": message,
            "timestamp": timestamp,
        }
        await self._redis.rpush(self._history_key(), json.dumps(event))
        await self._redis.ltrim(self._history_key(), -500, -1)  # Keep last 500 events
    
    async def record_reset(
        self,
        operator_id: str,
        timestamp: float,
    ) -> None:
        """Record a kill switch reset event."""
        event = {
            "type": "reset",
            "operator_id": operator_id,
            "timestamp": timestamp,
        }
        await self._redis.rpush(self._history_key(), json.dumps(event))
        await self._redis.ltrim(self._history_key(), -500, -1)
    
    async def get_history(self, limit: int = 100) -> list:
        """Get kill switch history."""
        events_raw = await self._redis.lrange(self._history_key(), -limit, -1)
        
        events = []
        for event_data in events_raw:
            try:
                if isinstance(event_data, bytes):
                    event_data = event_data.decode('utf-8')
                events.append(json.loads(event_data))
            except json.JSONDecodeError:
                continue
        
        return events


class PersistentKillSwitch:
    """
    Kill switch with Redis persistence.
    
    Wraps the core KillSwitch with persistence to ensure state
    survives restarts and is consistent across instances.
    """
    
    def __init__(
        self,
        clock,
        store: RedisKillSwitchStore,
        side_channel_publisher=None,
        alerts_client=None,
        tenant_id: str = "",
        bot_id: str = "",
    ):
        """
        Initialize persistent kill switch.
        
        Args:
            clock: Clock for timestamps
            store: Redis store for persistence
            side_channel_publisher: Optional publisher for events
            alerts_client: Optional AlertsClient for Slack/Discord notifications
            tenant_id: Tenant identifier for alerts
            bot_id: Bot identifier for alerts
        """
        self._clock = clock
        self._store = store
        self._publisher = side_channel_publisher
        self._alerts_client = alerts_client
        self._tenant_id = tenant_id
        self._bot_id = bot_id
        self._state: Optional[KillSwitchState] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Load state from Redis."""
        self._state = await self._store.load_state()
        self._initialized = True
        logger.info(
            f"Kill switch initialized: is_active={self._state.is_active}, "
            f"triggered_by={list(self._state.triggered_by.keys())}"
        )
    
    async def trigger(
        self,
        trigger: KillSwitchTrigger,
        message: str = "Kill switch activated",
    ) -> None:
        """
        Trigger the kill switch.
        
        Args:
            trigger: Trigger reason
            message: Human-readable message
        """
        if not self._initialized:
            await self.initialize()
        
        timestamp = self._clock.now()
        trigger_name = trigger.value if hasattr(trigger, 'value') else str(trigger)
        
        if not self._state.is_active:
            self._state.is_active = True
            self._state.message = message
            logger.critical(f"KILL SWITCH ACTIVATED by {trigger_name}: {message}")
        
        if trigger_name not in self._state.triggered_by:
            self._state.triggered_by[trigger_name] = timestamp
            logger.warning(f"Additional kill switch trigger: {trigger_name}")
        
        await self._store.save_state(self._state)
        await self._store.record_trigger(trigger_name, message, timestamp)
        
        # Publish event
        if self._publisher:
            await self._publish_event()
        
        # Send Slack/Discord alert
        if self._alerts_client:
            try:
                from quantgambit.observability.alerts import send_kill_switch_alert
                await send_kill_switch_alert(
                    client=self._alerts_client,
                    trigger=trigger_name,
                    message=message,
                    tenant_id=self._tenant_id,
                    bot_id=self._bot_id,
                    triggered_by=self._state.triggered_by,
                )
            except Exception as e:
                logger.error(f"Failed to send kill switch alert: {e}")
    
    async def reset(self, operator_id: str = "system") -> None:
        """
        Reset the kill switch.
        
        Args:
            operator_id: Who is resetting (for audit)
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._state.is_active:
            return
        
        timestamp = self._clock.now()
        
        self._state = KillSwitchState(
            is_active=False,
            triggered_by={},
            message="",
            last_reset_ts=timestamp,
            last_reset_by=operator_id,
        )
        
        await self._store.save_state(self._state)
        await self._store.record_reset(operator_id, timestamp)
        
        logger.warning(f"KILL SWITCH RESET by {operator_id}")
        
        if self._publisher:
            await self._publish_event()
        
        # Send Slack/Discord alert
        if self._alerts_client:
            try:
                from quantgambit.observability.alerts import send_kill_switch_reset_alert
                await send_kill_switch_reset_alert(
                    client=self._alerts_client,
                    operator_id=operator_id,
                    tenant_id=self._tenant_id,
                    bot_id=self._bot_id,
                )
            except Exception as e:
                logger.error(f"Failed to send kill switch reset alert: {e}")
    
    async def refresh_state(self) -> None:
        """Refresh state from Redis - call periodically to detect external changes."""
        if not self._initialized:
            await self.initialize()
            return
        
        new_state = await self._store.load_state()
        
        # Log state change if it differs
        if new_state.is_active != self._state.is_active:
            if new_state.is_active:
                logger.critical(
                    f"KILL SWITCH ACTIVATED (external): "
                    f"triggers={list(new_state.triggered_by.keys())}, "
                    f"message={new_state.message}"
                )
            else:
                logger.warning(
                    f"KILL SWITCH RESET (external) by {new_state.last_reset_by}"
                )
        
        self._state = new_state
    
    def is_active(self) -> bool:
        """Check if kill switch is active."""
        if not self._initialized or not self._state:
            return False
        return self._state.is_active
    
    async def is_active_async(self) -> bool:
        """
        Check if kill switch is active, refreshing from Redis first.
        
        Use this in hot path if you need fresh state.
        """
        await self.refresh_state()
        return self.is_active()
    
    def get_state(self) -> KillSwitchState:
        """Get current state."""
        if not self._state:
            return KillSwitchState()
        return self._state
    
    async def _publish_event(self) -> None:
        """Publish kill switch event to side channel."""
        if not self._publisher:
            return
        
        # Import here to avoid circular dependency
        from quantgambit.core.events import EventEnvelope, EventType
        
        event = EventEnvelope(
            v=1,
            type=EventType.OPS_KILL_SWITCH,
            source="quantgambit.risk.kill_switch",
            symbol=None,
            ts_wall=self._clock.now_wall(),
            ts_mono=self._clock.now_mono(),
            trace_id="kill_switch",
            seq=None,
            payload={
                "is_active": self._state.is_active,
                "triggered_by": self._state.triggered_by,
                "message": self._state.message,
                "last_reset_ts": self._state.last_reset_ts,
            },
        )
        self._publisher.publish(event)
