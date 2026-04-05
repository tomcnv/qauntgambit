"""
Configuration bundle lifecycle and audit.

Provides:
- Bundle creation with approval workflow
- Audit trail for config changes
- Rollback capability
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


class BundleStatus(str, Enum):
    """Configuration bundle status."""
    
    DRAFT = "draft"  # Being edited
    PENDING_APPROVAL = "pending_approval"  # Awaiting approval
    APPROVED = "approved"  # Approved for use
    ACTIVE = "active"  # Currently in use
    DEPRECATED = "deprecated"  # No longer recommended
    ROLLBACK = "rollback"  # Rolled back due to issues


@dataclass
class AuditEntry:
    """Audit log entry for bundle changes."""
    
    timestamp: str
    action: str  # create, submit, approve, reject, activate, deactivate, rollback
    actor: str  # Who performed the action
    bundle_id: str
    previous_status: Optional[str]
    new_status: str
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class ConfigBundle:
    """
    Versioned configuration bundle with lifecycle.
    
    Bundles go through: DRAFT -> PENDING_APPROVAL -> APPROVED -> ACTIVE
    """
    
    bundle_id: str
    version: str
    name: str
    description: str = ""
    
    # Version references
    feature_set_version_id: str = ""
    model_version_id: str = ""
    calibrator_version_id: str = ""
    risk_profile_version_id: str = ""
    execution_policy_version_id: str = ""
    
    # Status
    status: BundleStatus = BundleStatus.DRAFT
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    created_by: str = ""
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    activated_at: Optional[str] = None
    
    # Content hash for integrity
    content_hash: str = ""
    
    # Parent bundle (for rollback)
    parent_bundle_id: Optional[str] = None
    
    # Additional config
    config: Dict[str, Any] = field(default_factory=dict)
    
    def compute_hash(self) -> str:
        """Compute content hash."""
        content = {
            "feature_set_version_id": self.feature_set_version_id,
            "model_version_id": self.model_version_id,
            "calibrator_version_id": self.calibrator_version_id,
            "risk_profile_version_id": self.risk_profile_version_id,
            "execution_policy_version_id": self.execution_policy_version_id,
            "config": self.config,
        }
        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            **asdict(self),
            "status": self.status.value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfigBundle":
        """Create from dictionary."""
        data = dict(data)
        if isinstance(data.get("status"), str):
            data["status"] = BundleStatus(data["status"])
        return cls(**data)


class BundleStore(Protocol):
    """Protocol for bundle storage."""
    
    async def save(self, bundle: ConfigBundle) -> None:
        """Save bundle."""
        ...
    
    async def load(self, bundle_id: str) -> Optional[ConfigBundle]:
        """Load bundle by ID."""
        ...
    
    async def list_bundles(self, status: Optional[BundleStatus] = None) -> List[ConfigBundle]:
        """List bundles."""
        ...
    
    async def get_active(self) -> Optional[ConfigBundle]:
        """Get currently active bundle."""
        ...
    
    async def save_audit(self, entry: AuditEntry) -> None:
        """Save audit entry."""
        ...
    
    async def get_audit_log(self, bundle_id: str) -> List[AuditEntry]:
        """Get audit log for bundle."""
        ...


class ConfigBundleManager:
    """
    Manages configuration bundle lifecycle.
    
    Workflow:
    1. Create draft bundle
    2. Submit for approval
    3. Approve (or reject)
    4. Activate bundle
    5. Optionally rollback
    
    Usage:
        manager = ConfigBundleManager(store)
        
        # Create bundle
        bundle = await manager.create_bundle(
            name="Production v2",
            created_by="admin",
            feature_set_version_id="features_v1",
            model_version_id="model_v1",
            ...
        )
        
        # Submit for approval
        await manager.submit_for_approval(bundle.bundle_id, "admin")
        
        # Approve
        await manager.approve(bundle.bundle_id, "reviewer")
        
        # Activate
        await manager.activate(bundle.bundle_id, "deployer")
    """
    
    def __init__(self, store: BundleStore):
        """Initialize manager."""
        self._store = store
    
    async def create_bundle(
        self,
        name: str,
        created_by: str,
        feature_set_version_id: str = "",
        model_version_id: str = "",
        calibrator_version_id: str = "",
        risk_profile_version_id: str = "",
        execution_policy_version_id: str = "",
        description: str = "",
        config: Optional[Dict[str, Any]] = None,
        parent_bundle_id: Optional[str] = None,
    ) -> ConfigBundle:
        """
        Create a new configuration bundle.
        
        Args:
            name: Human-readable name
            created_by: Creator identifier
            feature_set_version_id: Feature set version
            model_version_id: Model version
            calibrator_version_id: Calibrator version
            risk_profile_version_id: Risk profile version
            execution_policy_version_id: Execution policy version
            description: Optional description
            config: Additional configuration
            parent_bundle_id: Parent bundle for inheritance
            
        Returns:
            Created ConfigBundle
        """
        # Generate bundle ID
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        bundle_id = f"bundle_{ts}_{hashlib.sha256(name.encode()).hexdigest()[:8]}"
        
        bundle = ConfigBundle(
            bundle_id=bundle_id,
            version="1.0.0",
            name=name,
            description=description,
            feature_set_version_id=feature_set_version_id,
            model_version_id=model_version_id,
            calibrator_version_id=calibrator_version_id,
            risk_profile_version_id=risk_profile_version_id,
            execution_policy_version_id=execution_policy_version_id,
            status=BundleStatus.DRAFT,
            created_by=created_by,
            parent_bundle_id=parent_bundle_id,
            config=config or {},
        )
        
        bundle.content_hash = bundle.compute_hash()
        
        await self._store.save(bundle)
        await self._audit("create", created_by, bundle, None, BundleStatus.DRAFT)
        
        logger.info(f"Created bundle {bundle_id}")
        return bundle
    
    async def submit_for_approval(
        self,
        bundle_id: str,
        submitted_by: str,
        notes: str = "",
    ) -> ConfigBundle:
        """Submit bundle for approval."""
        bundle = await self._store.load(bundle_id)
        if not bundle:
            raise ValueError(f"Bundle not found: {bundle_id}")
        
        if bundle.status != BundleStatus.DRAFT:
            raise ValueError(f"Cannot submit bundle in status {bundle.status}")
        
        prev_status = bundle.status
        bundle.status = BundleStatus.PENDING_APPROVAL
        
        await self._store.save(bundle)
        await self._audit("submit", submitted_by, bundle, prev_status, bundle.status, notes)
        
        logger.info(f"Bundle {bundle_id} submitted for approval")
        return bundle
    
    async def approve(
        self,
        bundle_id: str,
        approved_by: str,
        notes: str = "",
    ) -> ConfigBundle:
        """Approve a bundle."""
        bundle = await self._store.load(bundle_id)
        if not bundle:
            raise ValueError(f"Bundle not found: {bundle_id}")
        
        if bundle.status != BundleStatus.PENDING_APPROVAL:
            raise ValueError(f"Cannot approve bundle in status {bundle.status}")
        
        prev_status = bundle.status
        bundle.status = BundleStatus.APPROVED
        bundle.approved_at = datetime.utcnow().isoformat()
        bundle.approved_by = approved_by
        
        await self._store.save(bundle)
        await self._audit("approve", approved_by, bundle, prev_status, bundle.status, notes)
        
        logger.info(f"Bundle {bundle_id} approved by {approved_by}")
        return bundle
    
    async def reject(
        self,
        bundle_id: str,
        rejected_by: str,
        reason: str,
    ) -> ConfigBundle:
        """Reject a bundle."""
        bundle = await self._store.load(bundle_id)
        if not bundle:
            raise ValueError(f"Bundle not found: {bundle_id}")
        
        if bundle.status != BundleStatus.PENDING_APPROVAL:
            raise ValueError(f"Cannot reject bundle in status {bundle.status}")
        
        prev_status = bundle.status
        bundle.status = BundleStatus.DRAFT  # Back to draft for revision
        
        await self._store.save(bundle)
        await self._audit("reject", rejected_by, bundle, prev_status, bundle.status, reason)
        
        logger.info(f"Bundle {bundle_id} rejected: {reason}")
        return bundle
    
    async def activate(
        self,
        bundle_id: str,
        activated_by: str,
        notes: str = "",
    ) -> ConfigBundle:
        """Activate a bundle (make it the current active config)."""
        bundle = await self._store.load(bundle_id)
        if not bundle:
            raise ValueError(f"Bundle not found: {bundle_id}")
        
        if bundle.status not in {BundleStatus.APPROVED, BundleStatus.DEPRECATED}:
            raise ValueError(f"Cannot activate bundle in status {bundle.status}")
        
        # Deactivate current active bundle
        current_active = await self._store.get_active()
        if current_active and current_active.bundle_id != bundle_id:
            await self._deactivate(current_active.bundle_id, activated_by, "Superseded by " + bundle_id)
        
        prev_status = bundle.status
        bundle.status = BundleStatus.ACTIVE
        bundle.activated_at = datetime.utcnow().isoformat()
        
        await self._store.save(bundle)
        await self._audit("activate", activated_by, bundle, prev_status, bundle.status, notes)
        
        logger.info(f"Bundle {bundle_id} activated")
        return bundle
    
    async def _deactivate(
        self,
        bundle_id: str,
        deactivated_by: str,
        reason: str,
    ) -> ConfigBundle:
        """Deactivate a bundle."""
        bundle = await self._store.load(bundle_id)
        if not bundle:
            raise ValueError(f"Bundle not found: {bundle_id}")
        
        prev_status = bundle.status
        bundle.status = BundleStatus.DEPRECATED
        
        await self._store.save(bundle)
        await self._audit("deactivate", deactivated_by, bundle, prev_status, bundle.status, reason)
        
        logger.info(f"Bundle {bundle_id} deactivated")
        return bundle
    
    async def rollback(
        self,
        to_bundle_id: str,
        rolled_back_by: str,
        reason: str,
    ) -> ConfigBundle:
        """
        Rollback to a previous bundle.
        
        Deactivates current bundle and reactivates specified bundle.
        """
        target_bundle = await self._store.load(to_bundle_id)
        if not target_bundle:
            raise ValueError(f"Target bundle not found: {to_bundle_id}")
        
        current_active = await self._store.get_active()
        if current_active:
            # Mark current as rolled back
            prev_status = current_active.status
            current_active.status = BundleStatus.ROLLBACK
            await self._store.save(current_active)
            await self._audit("rollback", rolled_back_by, current_active, prev_status, 
                            current_active.status, f"Rolled back to {to_bundle_id}: {reason}")
        
        # Reactivate target
        prev_status = target_bundle.status
        target_bundle.status = BundleStatus.ACTIVE
        target_bundle.activated_at = datetime.utcnow().isoformat()
        
        await self._store.save(target_bundle)
        await self._audit("activate", rolled_back_by, target_bundle, prev_status, 
                         target_bundle.status, f"Rollback from previous: {reason}")
        
        logger.warning(f"Rolled back to bundle {to_bundle_id}")
        return target_bundle
    
    async def get_active_bundle(self) -> Optional[ConfigBundle]:
        """Get the currently active bundle."""
        return await self._store.get_active()
    
    async def get_audit_log(self, bundle_id: str) -> List[AuditEntry]:
        """Get audit log for a bundle."""
        return await self._store.get_audit_log(bundle_id)
    
    async def _audit(
        self,
        action: str,
        actor: str,
        bundle: ConfigBundle,
        prev_status: Optional[BundleStatus],
        new_status: BundleStatus,
        notes: str = "",
    ) -> None:
        """Record audit entry."""
        entry = AuditEntry(
            timestamp=datetime.utcnow().isoformat(),
            action=action,
            actor=actor,
            bundle_id=bundle.bundle_id,
            previous_status=prev_status.value if prev_status else None,
            new_status=new_status.value,
            notes=notes,
            metadata={
                "content_hash": bundle.content_hash,
                "version": bundle.version,
            },
        )
        await self._store.save_audit(entry)
