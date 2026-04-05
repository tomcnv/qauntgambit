"""
Artifact manifest for versioning and verification.

Each artifact (model, feature set, calibrator) has a manifest that
records its version, hash, and metadata for:
- Version tracking
- Integrity verification
- Audit trail
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ArtifactManifest:
    """
    Manifest for a versioned artifact.
    
    Attributes:
        artifact_type: Type of artifact (model, feature_set, calibrator, etc.)
        version_id: Unique version identifier
        name: Human-readable name
        description: Description of the artifact
        created_at: Creation timestamp
        hash_sha256: SHA-256 hash of artifact content
        dependencies: List of dependency version IDs
        metadata: Additional metadata
    """
    
    artifact_type: str
    version_id: str
    name: str
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    hash_sha256: str = ""
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "artifact_type": self.artifact_type,
            "version_id": self.version_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "hash_sha256": self.hash_sha256,
            "dependencies": self.dependencies,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactManifest":
        """Create from dictionary."""
        return cls(
            artifact_type=data["artifact_type"],
            version_id=data["version_id"],
            name=data["name"],
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
            hash_sha256=data.get("hash_sha256", ""),
            dependencies=data.get("dependencies", []),
            metadata=data.get("metadata", {}),
        )


class ArtifactRegistry:
    """
    Registry for artifact manifests.
    
    Provides:
    - Registration and lookup of artifacts
    - Hash verification
    - Dependency resolution
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        """Initialize registry."""
        self._manifests: Dict[str, ArtifactManifest] = {}
        self._storage_path = storage_path
        
        if storage_path and storage_path.exists():
            self._load_from_storage()
    
    def register(self, manifest: ArtifactManifest) -> None:
        """
        Register an artifact manifest.
        
        Args:
            manifest: Manifest to register
        """
        key = f"{manifest.artifact_type}:{manifest.version_id}"
        self._manifests[key] = manifest
        self._save_to_storage()
    
    def get(
        self,
        artifact_type: str,
        version_id: str,
    ) -> Optional[ArtifactManifest]:
        """
        Get artifact manifest.
        
        Args:
            artifact_type: Type of artifact
            version_id: Version identifier
            
        Returns:
            Manifest if found, None otherwise
        """
        key = f"{artifact_type}:{version_id}"
        return self._manifests.get(key)
    
    def get_latest(self, artifact_type: str) -> Optional[ArtifactManifest]:
        """
        Get latest manifest for an artifact type.
        
        Args:
            artifact_type: Type of artifact
            
        Returns:
            Latest manifest if found, None otherwise
        """
        matching = [
            m for k, m in self._manifests.items()
            if m.artifact_type == artifact_type
        ]
        if not matching:
            return None
        
        # Sort by created_at (newest first)
        return max(matching, key=lambda m: m.created_at)
    
    def list_versions(self, artifact_type: str) -> List[str]:
        """
        List all versions for an artifact type.
        
        Args:
            artifact_type: Type of artifact
            
        Returns:
            List of version IDs
        """
        return [
            m.version_id for m in self._manifests.values()
            if m.artifact_type == artifact_type
        ]
    
    def verify_hash(
        self,
        artifact_type: str,
        version_id: str,
        content: bytes,
    ) -> bool:
        """
        Verify artifact content matches registered hash.
        
        Args:
            artifact_type: Type of artifact
            version_id: Version identifier
            content: Artifact content bytes
            
        Returns:
            True if hash matches
        """
        manifest = self.get(artifact_type, version_id)
        if not manifest:
            return False
        
        actual_hash = hashlib.sha256(content).hexdigest()
        return actual_hash == manifest.hash_sha256
    
    def resolve_dependencies(
        self,
        artifact_type: str,
        version_id: str,
    ) -> List[ArtifactManifest]:
        """
        Resolve all dependencies for an artifact.
        
        Args:
            artifact_type: Type of artifact
            version_id: Version identifier
            
        Returns:
            List of dependency manifests (in dependency order)
        """
        manifest = self.get(artifact_type, version_id)
        if not manifest:
            return []
        
        resolved = []
        for dep_id in manifest.dependencies:
            # Parse dependency ID (format: "type:version")
            parts = dep_id.split(":", 1)
            if len(parts) != 2:
                continue
            
            dep_type, dep_version = parts
            dep_manifest = self.get(dep_type, dep_version)
            if dep_manifest:
                # Recursively resolve
                resolved.extend(self.resolve_dependencies(dep_type, dep_version))
                resolved.append(dep_manifest)
        
        return resolved
    
    def _load_from_storage(self) -> None:
        """Load manifests from storage."""
        if not self._storage_path:
            return
        
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            
            for item in data.get("manifests", []):
                manifest = ArtifactManifest.from_dict(item)
                key = f"{manifest.artifact_type}:{manifest.version_id}"
                self._manifests[key] = manifest
                
        except (IOError, json.JSONDecodeError) as e:
            # Log but don't fail
            pass
    
    def _save_to_storage(self) -> None:
        """Save manifests to storage."""
        if not self._storage_path:
            return
        
        try:
            data = {
                "manifests": [m.to_dict() for m in self._manifests.values()],
                "updated_at": datetime.utcnow().isoformat(),
            }
            
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2)
                
        except IOError as e:
            # Log but don't fail
            pass


def compute_artifact_hash(content: bytes) -> str:
    """
    Compute SHA-256 hash for artifact content.
    
    Args:
        content: Artifact content bytes
        
    Returns:
        Hex-encoded hash string
    """
    return hashlib.sha256(content).hexdigest()


def create_model_manifest(
    version_id: str,
    name: str,
    model_path: Path,
    feature_set_version_id: str,
    description: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> ArtifactManifest:
    """
    Create manifest for a model artifact.
    
    Args:
        version_id: Version identifier
        name: Model name
        model_path: Path to model file
        feature_set_version_id: Feature set this model expects
        description: Model description
        metadata: Additional metadata
        
    Returns:
        ArtifactManifest
    """
    content = model_path.read_bytes()
    hash_sha256 = compute_artifact_hash(content)
    
    return ArtifactManifest(
        artifact_type="model",
        version_id=version_id,
        name=name,
        description=description,
        hash_sha256=hash_sha256,
        dependencies=[f"feature_set:{feature_set_version_id}"],
        metadata=metadata or {},
    )


def create_feature_set_manifest(
    version_id: str,
    name: str,
    feature_names: List[str],
    description: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> ArtifactManifest:
    """
    Create manifest for a feature set artifact.
    
    Args:
        version_id: Version identifier
        name: Feature set name
        feature_names: List of feature names
        description: Description
        metadata: Additional metadata
        
    Returns:
        ArtifactManifest
    """
    # Hash the feature names as content
    content = json.dumps(sorted(feature_names)).encode()
    hash_sha256 = compute_artifact_hash(content)
    
    return ArtifactManifest(
        artifact_type="feature_set",
        version_id=version_id,
        name=name,
        description=description,
        hash_sha256=hash_sha256,
        dependencies=[],
        metadata={
            "feature_count": len(feature_names),
            "feature_names": feature_names,
            **(metadata or {}),
        },
    )


def create_calibrator_manifest(
    version_id: str,
    name: str,
    calibrator_path: Path,
    model_version_id: str,
    description: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> ArtifactManifest:
    """
    Create manifest for a calibrator artifact.
    
    Args:
        version_id: Version identifier
        name: Calibrator name
        calibrator_path: Path to calibrator file
        model_version_id: Model this calibrator is trained for
        description: Description
        metadata: Additional metadata
        
    Returns:
        ArtifactManifest
    """
    content = calibrator_path.read_bytes()
    hash_sha256 = compute_artifact_hash(content)
    
    return ArtifactManifest(
        artifact_type="calibrator",
        version_id=version_id,
        name=name,
        description=description,
        hash_sha256=hash_sha256,
        dependencies=[f"model:{model_version_id}"],
        metadata=metadata or {},
    )
