"""
Redis-backed configuration bundle store.

Production-ready persistence for config bundles with audit trail.
"""

import json
import logging
from typing import Dict, List, Optional

from quantgambit.core.config.audit import (
    AuditEntry,
    BundleStatus,
    BundleStore,
    ConfigBundle,
)

logger = logging.getLogger(__name__)


class RedisBundleStore(BundleStore):
    """
    Redis-backed bundle store for production use.
    
    Storage scheme:
    - quantgambit:{tenant_id}:config:bundles:{bundle_id} -> bundle JSON
    - quantgambit:{tenant_id}:config:bundles:index -> set of bundle IDs
    - quantgambit:{tenant_id}:config:bundles:active -> active bundle ID
    - quantgambit:{tenant_id}:config:audit:{bundle_id} -> list of audit entries
    """
    
    def __init__(self, redis_client, tenant_id: str):
        """
        Initialize Redis bundle store.
        
        Args:
            redis_client: Async Redis client
            tenant_id: Tenant identifier for namespacing
        """
        self._redis = redis_client
        self._tenant_id = tenant_id
        self._prefix = f"quantgambit:{tenant_id}:config"
    
    def _bundle_key(self, bundle_id: str) -> str:
        return f"{self._prefix}:bundles:{bundle_id}"
    
    def _index_key(self) -> str:
        return f"{self._prefix}:bundles:index"
    
    def _active_key(self) -> str:
        return f"{self._prefix}:bundles:active"
    
    def _audit_key(self, bundle_id: str) -> str:
        return f"{self._prefix}:audit:{bundle_id}"
    
    async def save(self, bundle: ConfigBundle) -> None:
        """Save bundle to Redis."""
        key = self._bundle_key(bundle.bundle_id)
        data = bundle.to_dict()
        await self._redis.set(key, json.dumps(data))
        
        # Add to index
        await self._redis.sadd(self._index_key(), bundle.bundle_id)
        
        # Update active pointer if needed
        if bundle.status == BundleStatus.ACTIVE:
            await self._redis.set(self._active_key(), bundle.bundle_id)
        
        logger.debug(f"Saved bundle {bundle.bundle_id} with status {bundle.status}")
    
    async def load(self, bundle_id: str) -> Optional[ConfigBundle]:
        """Load bundle from Redis."""
        key = self._bundle_key(bundle_id)
        data = await self._redis.get(key)
        
        if not data:
            return None
        
        try:
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            bundle_dict = json.loads(data)
            return ConfigBundle.from_dict(bundle_dict)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load bundle {bundle_id}: {e}")
            return None
    
    async def list_bundles(self, status: Optional[BundleStatus] = None) -> List[ConfigBundle]:
        """List all bundles, optionally filtered by status."""
        bundle_ids = await self._redis.smembers(self._index_key())
        
        bundles = []
        for bid in bundle_ids:
            if isinstance(bid, bytes):
                bid = bid.decode('utf-8')
            bundle = await self.load(bid)
            if bundle:
                if status is None or bundle.status == status:
                    bundles.append(bundle)
        
        # Sort by created_at descending
        bundles.sort(key=lambda b: b.created_at, reverse=True)
        return bundles
    
    async def get_active(self) -> Optional[ConfigBundle]:
        """Get currently active bundle."""
        active_id = await self._redis.get(self._active_key())
        
        if not active_id:
            return None
        
        if isinstance(active_id, bytes):
            active_id = active_id.decode('utf-8')
        
        return await self.load(active_id)
    
    async def save_audit(self, entry: AuditEntry) -> None:
        """Save audit entry to Redis."""
        key = self._audit_key(entry.bundle_id)
        data = json.dumps(entry.to_dict())
        await self._redis.rpush(key, data)
        
        # Keep audit log bounded (last 1000 entries per bundle)
        await self._redis.ltrim(key, -1000, -1)
    
    async def get_audit_log(self, bundle_id: str) -> List[AuditEntry]:
        """Get audit log for a bundle."""
        key = self._audit_key(bundle_id)
        entries_raw = await self._redis.lrange(key, 0, -1)
        
        entries = []
        for entry_data in entries_raw:
            try:
                if isinstance(entry_data, bytes):
                    entry_data = entry_data.decode('utf-8')
                entry_dict = json.loads(entry_data)
                entries.append(AuditEntry(**entry_dict))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse audit entry: {e}")
        
        return entries
    
    async def delete(self, bundle_id: str) -> bool:
        """Delete a bundle (soft delete - keeps audit log)."""
        bundle = await self.load(bundle_id)
        if not bundle:
            return False
        
        # Remove from active if needed
        active_id = await self._redis.get(self._active_key())
        if active_id:
            if isinstance(active_id, bytes):
                active_id = active_id.decode('utf-8')
            if active_id == bundle_id:
                await self._redis.delete(self._active_key())
        
        # Remove bundle
        await self._redis.delete(self._bundle_key(bundle_id))
        await self._redis.srem(self._index_key(), bundle_id)
        
        return True
