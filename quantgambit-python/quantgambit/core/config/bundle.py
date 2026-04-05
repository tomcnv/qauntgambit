"""
Versioned configuration bundles.

Every decision references a ConfigBundle that pins the exact versions
of all configuration components used. This enables:
- Reproducible decisions
- Audit trail
- A/B testing
- Rollback capability

Each config object has:
- id (UUID)
- name + revision
- content_json
- content_hash (SHA256)
- created_at
- created_by
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import hashlib
import json
import uuid

from quantgambit.core.clock import get_clock


@dataclass(frozen=True)
class ConfigObject:
    """
    A versioned configuration object.
    
    Immutable after creation. The content_hash ensures integrity.
    
    Attributes:
        id: Unique identifier (UUID)
        name: Human-readable name
        revision: Version number or semver
        content_json: JSON-serialized configuration
        content_hash: SHA256 hash of content_json
        created_at: Creation timestamp (epoch seconds)
        created_by: Creator identifier
        git_commit: Optional git commit hash
    """
    
    id: str
    name: str
    revision: str
    content_json: str
    content_hash: str
    created_at: float
    created_by: str
    git_commit: Optional[str] = None
    
    @classmethod
    def create(
        cls,
        name: str,
        revision: str,
        content: Dict[str, Any],
        created_by: str,
        git_commit: Optional[str] = None,
    ) -> "ConfigObject":
        """
        Create a new config object.
        
        Args:
            name: Config name
            revision: Version string
            content: Configuration dictionary
            created_by: Creator identifier
            git_commit: Optional git commit
            
        Returns:
            New ConfigObject with computed hash
        """
        content_json = json.dumps(content, sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256(content_json.encode()).hexdigest()
        
        return cls(
            id=str(uuid.uuid4()),
            name=name,
            revision=revision,
            content_json=content_json,
            content_hash=content_hash,
            created_at=get_clock().now_wall(),
            created_by=created_by,
            git_commit=git_commit,
        )
    
    def get_content(self) -> Dict[str, Any]:
        """Parse and return the content dictionary."""
        return json.loads(self.content_json)
    
    def verify_hash(self) -> bool:
        """Verify content hash matches content."""
        computed = hashlib.sha256(self.content_json.encode()).hexdigest()
        return computed == self.content_hash
    
    def version_id(self) -> str:
        """Get version identifier (name:revision:hash_prefix)."""
        return f"{self.name}:{self.revision}:{self.content_hash[:8]}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "revision": self.revision,
            "content_json": self.content_json,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "git_commit": self.git_commit,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfigObject":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            revision=data["revision"],
            content_json=data["content_json"],
            content_hash=data["content_hash"],
            created_at=data["created_at"],
            created_by=data["created_by"],
            git_commit=data.get("git_commit"),
        )


def create_config_object(
    name: str,
    revision: str,
    content: Dict[str, Any],
    created_by: str = "system",
    git_commit: Optional[str] = None,
) -> ConfigObject:
    """
    Convenience function to create a config object.
    
    Args:
        name: Config name
        revision: Version string
        content: Configuration dictionary
        created_by: Creator identifier
        git_commit: Optional git commit
        
    Returns:
        New ConfigObject
    """
    return ConfigObject.create(
        name=name,
        revision=revision,
        content=content,
        created_by=created_by,
        git_commit=git_commit,
    )


@dataclass(frozen=True)
class ConfigBundle:
    """
    Complete configuration bundle for a runtime session.
    
    Pins all component versions used during a session.
    Every DecisionRecord references this bundle's ID.
    
    Attributes:
        bundle_id: Unique bundle identifier
        feature_set_version_id: Feature set version
        model_version_id: Model artifact version
        calibrator_version_id: Calibrator version
        risk_profile_version_id: Risk profile version
        execution_policy_version_id: Execution policy version
        created_at: Bundle creation timestamp
        git_commit: Optional git commit of runtime
    """
    
    bundle_id: str
    feature_set_version_id: str
    model_version_id: str
    calibrator_version_id: str
    risk_profile_version_id: str
    execution_policy_version_id: str
    created_at: float
    git_commit: Optional[str] = None
    
    @classmethod
    def create(
        cls,
        feature_set: ConfigObject,
        model: ConfigObject,
        calibrator: ConfigObject,
        risk_profile: ConfigObject,
        execution_policy: ConfigObject,
        git_commit: Optional[str] = None,
    ) -> "ConfigBundle":
        """
        Create a bundle from config objects.
        
        Args:
            feature_set: Feature set config
            model: Model config
            calibrator: Calibrator config
            risk_profile: Risk profile config
            execution_policy: Execution policy config
            git_commit: Optional git commit
            
        Returns:
            New ConfigBundle
        """
        return cls(
            bundle_id=str(uuid.uuid4()),
            feature_set_version_id=feature_set.version_id(),
            model_version_id=model.version_id(),
            calibrator_version_id=calibrator.version_id(),
            risk_profile_version_id=risk_profile.version_id(),
            execution_policy_version_id=execution_policy.version_id(),
            created_at=get_clock().now_wall(),
            git_commit=git_commit,
        )
    
    @classmethod
    def create_from_ids(
        cls,
        feature_set_version_id: str,
        model_version_id: str,
        calibrator_version_id: str,
        risk_profile_version_id: str,
        execution_policy_version_id: str,
        git_commit: Optional[str] = None,
    ) -> "ConfigBundle":
        """
        Create a bundle from version IDs directly.
        
        Args:
            feature_set_version_id: Feature set version ID
            model_version_id: Model version ID
            calibrator_version_id: Calibrator version ID
            risk_profile_version_id: Risk profile version ID
            execution_policy_version_id: Execution policy version ID
            git_commit: Optional git commit
            
        Returns:
            New ConfigBundle
        """
        return cls(
            bundle_id=str(uuid.uuid4()),
            feature_set_version_id=feature_set_version_id,
            model_version_id=model_version_id,
            calibrator_version_id=calibrator_version_id,
            risk_profile_version_id=risk_profile_version_id,
            execution_policy_version_id=execution_policy_version_id,
            created_at=get_clock().now_wall(),
            git_commit=git_commit,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "bundle_id": self.bundle_id,
            "feature_set_version_id": self.feature_set_version_id,
            "model_version_id": self.model_version_id,
            "calibrator_version_id": self.calibrator_version_id,
            "risk_profile_version_id": self.risk_profile_version_id,
            "execution_policy_version_id": self.execution_policy_version_id,
            "created_at": self.created_at,
            "git_commit": self.git_commit,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfigBundle":
        """Deserialize from dictionary."""
        return cls(
            bundle_id=data["bundle_id"],
            feature_set_version_id=data["feature_set_version_id"],
            model_version_id=data["model_version_id"],
            calibrator_version_id=data["calibrator_version_id"],
            risk_profile_version_id=data["risk_profile_version_id"],
            execution_policy_version_id=data["execution_policy_version_id"],
            created_at=data["created_at"],
            git_commit=data.get("git_commit"),
        )
    
    def summary(self) -> str:
        """Get human-readable summary."""
        return (
            f"ConfigBundle({self.bundle_id[:8]}): "
            f"features={self.feature_set_version_id}, "
            f"model={self.model_version_id}, "
            f"risk={self.risk_profile_version_id}"
        )
