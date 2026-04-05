"""
In-memory configuration bundle store.

For production, replace with Redis/database-backed implementation.
"""

from typing import Dict, List, Optional

from quantgambit.core.config.audit import (
    AuditEntry,
    BundleStatus,
    BundleStore,
    ConfigBundle,
)


class InMemoryBundleStore(BundleStore):
    """
    In-memory bundle store for development/testing.
    
    NOT for production - data lost on restart.
    """
    
    def __init__(self):
        self._bundles: Dict[str, ConfigBundle] = {}
        self._audit_log: Dict[str, List[AuditEntry]] = {}  # bundle_id -> entries
    
    async def save(self, bundle: ConfigBundle) -> None:
        """Save bundle."""
        self._bundles[bundle.bundle_id] = bundle
    
    async def load(self, bundle_id: str) -> Optional[ConfigBundle]:
        """Load bundle by ID."""
        return self._bundles.get(bundle_id)
    
    async def list_bundles(self, status: Optional[BundleStatus] = None) -> List[ConfigBundle]:
        """List bundles, optionally filtered by status."""
        bundles = list(self._bundles.values())
        if status:
            bundles = [b for b in bundles if b.status == status]
        return bundles
    
    async def get_active(self) -> Optional[ConfigBundle]:
        """Get currently active bundle."""
        for bundle in self._bundles.values():
            if bundle.status == BundleStatus.ACTIVE:
                return bundle
        return None
    
    async def save_audit(self, entry: AuditEntry) -> None:
        """Save audit entry."""
        if entry.bundle_id not in self._audit_log:
            self._audit_log[entry.bundle_id] = []
        self._audit_log[entry.bundle_id].append(entry)
    
    async def get_audit_log(self, bundle_id: str) -> List[AuditEntry]:
        """Get audit log for bundle."""
        return self._audit_log.get(bundle_id, [])
