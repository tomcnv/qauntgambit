"""
Unit tests for configuration bundle lifecycle and audit.

Tests:
- Bundle creation
- Approval workflow
- Activation/deactivation
- Rollback
- Audit trail
"""

import pytest
from quantgambit.core.config.audit import (
    ConfigBundle,
    BundleStatus,
    ConfigBundleManager,
    AuditEntry,
)
from quantgambit.core.config.store import InMemoryBundleStore


@pytest.fixture
def store() -> InMemoryBundleStore:
    return InMemoryBundleStore()


@pytest.fixture
def manager(store) -> ConfigBundleManager:
    return ConfigBundleManager(store)


class TestConfigBundleCreation:
    """Tests for bundle creation."""
    
    @pytest.mark.asyncio
    async def test_create_bundle(self, manager):
        """Should create a new bundle in DRAFT status."""
        bundle = await manager.create_bundle(
            name="Test Bundle",
            created_by="admin",
            feature_set_version_id="features_v1",
            model_version_id="model_v1",
            description="Test description",
        )
        
        assert bundle.name == "Test Bundle"
        assert bundle.status == BundleStatus.DRAFT
        assert bundle.created_by == "admin"
        assert bundle.feature_set_version_id == "features_v1"
        assert bundle.content_hash  # Should have hash
    
    @pytest.mark.asyncio
    async def test_create_bundle_generates_unique_id(self, manager):
        """Each bundle should have unique ID."""
        bundle1 = await manager.create_bundle(name="Bundle 1", created_by="admin")
        bundle2 = await manager.create_bundle(name="Bundle 2", created_by="admin")
        
        assert bundle1.bundle_id != bundle2.bundle_id


class TestApprovalWorkflow:
    """Tests for approval workflow."""
    
    @pytest.mark.asyncio
    async def test_submit_for_approval(self, manager):
        """Should transition from DRAFT to PENDING_APPROVAL."""
        bundle = await manager.create_bundle(name="Test", created_by="admin")
        
        updated = await manager.submit_for_approval(bundle.bundle_id, "admin")
        
        assert updated.status == BundleStatus.PENDING_APPROVAL
    
    @pytest.mark.asyncio
    async def test_cannot_submit_non_draft(self, manager):
        """Should not allow submitting non-draft bundle."""
        bundle = await manager.create_bundle(name="Test", created_by="admin")
        await manager.submit_for_approval(bundle.bundle_id, "admin")
        
        with pytest.raises(ValueError, match="Cannot submit"):
            await manager.submit_for_approval(bundle.bundle_id, "admin")
    
    @pytest.mark.asyncio
    async def test_approve_bundle(self, manager):
        """Should transition from PENDING_APPROVAL to APPROVED."""
        bundle = await manager.create_bundle(name="Test", created_by="admin")
        await manager.submit_for_approval(bundle.bundle_id, "admin")
        
        approved = await manager.approve(bundle.bundle_id, "reviewer")
        
        assert approved.status == BundleStatus.APPROVED
        assert approved.approved_by == "reviewer"
        assert approved.approved_at is not None
    
    @pytest.mark.asyncio
    async def test_reject_bundle(self, manager):
        """Should transition from PENDING_APPROVAL back to DRAFT."""
        bundle = await manager.create_bundle(name="Test", created_by="admin")
        await manager.submit_for_approval(bundle.bundle_id, "admin")
        
        rejected = await manager.reject(bundle.bundle_id, "reviewer", "Needs changes")
        
        assert rejected.status == BundleStatus.DRAFT


class TestActivation:
    """Tests for bundle activation."""
    
    @pytest.mark.asyncio
    async def test_activate_approved_bundle(self, manager):
        """Should activate an approved bundle."""
        bundle = await manager.create_bundle(name="Test", created_by="admin")
        await manager.submit_for_approval(bundle.bundle_id, "admin")
        await manager.approve(bundle.bundle_id, "reviewer")
        
        activated = await manager.activate(bundle.bundle_id, "deployer")
        
        assert activated.status == BundleStatus.ACTIVE
        assert activated.activated_at is not None
    
    @pytest.mark.asyncio
    async def test_cannot_activate_draft(self, manager):
        """Should not allow activating draft bundle."""
        bundle = await manager.create_bundle(name="Test", created_by="admin")
        
        with pytest.raises(ValueError, match="Cannot activate"):
            await manager.activate(bundle.bundle_id, "deployer")
    
    @pytest.mark.asyncio
    async def test_activating_new_deactivates_old(self, manager):
        """Activating a new bundle should deactivate the current one."""
        # Create and activate first bundle
        bundle1 = await manager.create_bundle(name="Bundle 1", created_by="admin")
        await manager.submit_for_approval(bundle1.bundle_id, "admin")
        await manager.approve(bundle1.bundle_id, "reviewer")
        await manager.activate(bundle1.bundle_id, "deployer")
        
        # Create and activate second bundle
        bundle2 = await manager.create_bundle(name="Bundle 2", created_by="admin")
        await manager.submit_for_approval(bundle2.bundle_id, "admin")
        await manager.approve(bundle2.bundle_id, "reviewer")
        await manager.activate(bundle2.bundle_id, "deployer")
        
        # First should be deprecated
        active = await manager.get_active_bundle()
        assert active.bundle_id == bundle2.bundle_id
    
    @pytest.mark.asyncio
    async def test_get_active_bundle(self, manager):
        """Should return currently active bundle."""
        bundle = await manager.create_bundle(name="Test", created_by="admin")
        await manager.submit_for_approval(bundle.bundle_id, "admin")
        await manager.approve(bundle.bundle_id, "reviewer")
        await manager.activate(bundle.bundle_id, "deployer")
        
        active = await manager.get_active_bundle()
        
        assert active is not None
        assert active.bundle_id == bundle.bundle_id


class TestRollback:
    """Tests for rollback functionality."""
    
    @pytest.mark.asyncio
    async def test_rollback_to_previous(self, manager):
        """Should rollback to a previous bundle."""
        # Create and activate first bundle
        bundle1 = await manager.create_bundle(name="Bundle 1", created_by="admin")
        await manager.submit_for_approval(bundle1.bundle_id, "admin")
        await manager.approve(bundle1.bundle_id, "reviewer")
        await manager.activate(bundle1.bundle_id, "deployer")
        
        # Create and activate second bundle
        bundle2 = await manager.create_bundle(name="Bundle 2", created_by="admin")
        await manager.submit_for_approval(bundle2.bundle_id, "admin")
        await manager.approve(bundle2.bundle_id, "reviewer")
        await manager.activate(bundle2.bundle_id, "deployer")
        
        # Rollback to first
        rolled_back = await manager.rollback(bundle1.bundle_id, "ops", "Bug in bundle 2")
        
        assert rolled_back.bundle_id == bundle1.bundle_id
        assert rolled_back.status == BundleStatus.ACTIVE
        
        active = await manager.get_active_bundle()
        assert active.bundle_id == bundle1.bundle_id


class TestAuditTrail:
    """Tests for audit trail."""
    
    @pytest.mark.asyncio
    async def test_audit_entries_created(self, manager):
        """Should create audit entries for all actions."""
        bundle = await manager.create_bundle(name="Test", created_by="admin")
        await manager.submit_for_approval(bundle.bundle_id, "admin")
        await manager.approve(bundle.bundle_id, "reviewer")
        await manager.activate(bundle.bundle_id, "deployer")
        
        audit_log = await manager.get_audit_log(bundle.bundle_id)
        
        assert len(audit_log) == 4  # create, submit, approve, activate
        
        actions = [entry.action for entry in audit_log]
        assert "create" in actions
        assert "submit" in actions
        assert "approve" in actions
        assert "activate" in actions
    
    @pytest.mark.asyncio
    async def test_audit_entry_contains_actor(self, manager):
        """Audit entries should contain actor information."""
        bundle = await manager.create_bundle(name="Test", created_by="admin")
        
        audit_log = await manager.get_audit_log(bundle.bundle_id)
        
        assert audit_log[0].actor == "admin"
    
    @pytest.mark.asyncio
    async def test_audit_entry_contains_timestamps(self, manager):
        """Audit entries should have timestamps."""
        bundle = await manager.create_bundle(name="Test", created_by="admin")
        
        audit_log = await manager.get_audit_log(bundle.bundle_id)
        
        assert audit_log[0].timestamp is not None


class TestContentHash:
    """Tests for content hash computation."""
    
    @pytest.mark.asyncio
    async def test_same_content_same_hash(self, manager):
        """Bundles with same content should have same hash."""
        bundle1 = await manager.create_bundle(
            name="Bundle 1",
            created_by="admin",
            feature_set_version_id="features_v1",
            model_version_id="model_v1",
        )
        bundle2 = await manager.create_bundle(
            name="Bundle 2",  # Different name
            created_by="admin",
            feature_set_version_id="features_v1",  # Same content
            model_version_id="model_v1",
        )
        
        # Same content should produce same hash
        assert bundle1.content_hash == bundle2.content_hash
    
    @pytest.mark.asyncio
    async def test_different_content_different_hash(self, manager):
        """Bundles with different content should have different hash."""
        bundle1 = await manager.create_bundle(
            name="Bundle 1",
            created_by="admin",
            feature_set_version_id="features_v1",
        )
        bundle2 = await manager.create_bundle(
            name="Bundle 2",
            created_by="admin",
            feature_set_version_id="features_v2",  # Different
        )
        
        assert bundle1.content_hash != bundle2.content_hash


class TestBundleSerialization:
    """Tests for bundle serialization."""
    
    def test_to_dict(self):
        """Should serialize bundle to dictionary."""
        bundle = ConfigBundle(
            bundle_id="test_123",
            version="1.0.0",
            name="Test Bundle",
            feature_set_version_id="features_v1",
            status=BundleStatus.ACTIVE,
        )
        
        data = bundle.to_dict()
        
        assert data["bundle_id"] == "test_123"
        assert data["status"] == "active"
        assert data["feature_set_version_id"] == "features_v1"
    
    def test_from_dict(self):
        """Should deserialize bundle from dictionary."""
        data = {
            "bundle_id": "test_123",
            "version": "1.0.0",
            "name": "Test Bundle",
            "description": "",
            "feature_set_version_id": "features_v1",
            "model_version_id": "",
            "calibrator_version_id": "",
            "risk_profile_version_id": "",
            "execution_policy_version_id": "",
            "status": "active",
            "created_at": "2024-01-01T00:00:00",
            "created_by": "admin",
            "approved_at": None,
            "approved_by": None,
            "activated_at": None,
            "content_hash": "abc123",
            "parent_bundle_id": None,
            "config": {},
        }
        
        bundle = ConfigBundle.from_dict(data)
        
        assert bundle.bundle_id == "test_123"
        assert bundle.status == BundleStatus.ACTIVE
