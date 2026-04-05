"""Configuration version management for trading pipeline integration.

This module provides versioned configuration snapshots for ensuring parity
between live trading and backtest systems.

Feature: trading-pipeline-integration
Requirements: 1.6 - THE System SHALL version all configuration changes with timestamps
              and store them in the database for historical comparison
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class ConfigVersion:
    """Versioned configuration snapshot.
    
    Represents a point-in-time snapshot of trading configuration parameters.
    Each version is uniquely identified and can be retrieved for historical
    comparison or replay purposes.
    
    Feature: trading-pipeline-integration
    Requirements: 1.6
    
    Attributes:
        version_id: Unique identifier for this configuration version
        created_at: Timestamp when this version was created
        created_by: Source of the configuration ("live", "backtest", "optimizer")
        config_hash: Deterministic hash of the parameters for quick comparison
        parameters: Dictionary of all configuration parameters
    """
    version_id: str
    created_at: datetime
    created_by: str  # "live", "backtest", "optimizer"
    config_hash: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Validate the ConfigVersion after initialization."""
        if not self.version_id:
            raise ValueError("version_id cannot be empty")
        if not self.created_by:
            raise ValueError("created_by cannot be empty")
        if self.created_by not in ("live", "backtest", "optimizer"):
            raise ValueError(
                f"created_by must be 'live', 'backtest', or 'optimizer', got '{self.created_by}'"
            )
        # Ensure created_at has timezone info
        if self.created_at.tzinfo is None:
            object.__setattr__(
                self, 
                'created_at', 
                self.created_at.replace(tzinfo=timezone.utc)
            )
    
    @classmethod
    def create(
        cls,
        version_id: str,
        created_by: str,
        parameters: Dict[str, Any],
        created_at: Optional[datetime] = None,
    ) -> "ConfigVersion":
        """Create a new ConfigVersion with computed hash.
        
        Args:
            version_id: Unique identifier for this version
            created_by: Source of the configuration
            parameters: Configuration parameters dictionary
            created_at: Optional timestamp (defaults to now)
            
        Returns:
            New ConfigVersion instance with computed config_hash
        """
        if created_at is None:
            created_at = datetime.now(timezone.utc)
        
        config_hash = cls.compute_hash(parameters)
        
        return cls(
            version_id=version_id,
            created_at=created_at,
            created_by=created_by,
            config_hash=config_hash,
            parameters=parameters,
        )
    
    @staticmethod
    def compute_hash(parameters: Dict[str, Any]) -> str:
        """Compute a deterministic hash of configuration parameters.
        
        Args:
            parameters: Configuration parameters dictionary
            
        Returns:
            16-character hex hash string
        """
        # Sort keys and use default=str for non-serializable types
        serialized = json.dumps(parameters, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation of the ConfigVersion
        """
        return {
            "version_id": self.version_id,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "config_hash": self.config_hash,
            "parameters": self.parameters,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfigVersion":
        """Create ConfigVersion from dictionary.
        
        Args:
            data: Dictionary with ConfigVersion fields
            
        Returns:
            ConfigVersion instance
        """
        created_at = data["created_at"]
        if isinstance(created_at, str):
            # Parse ISO format string
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        
        return cls(
            version_id=data["version_id"],
            created_at=created_at,
            created_by=data["created_by"],
            config_hash=data["config_hash"],
            parameters=data.get("parameters", {}),
        )


class ConfigVersionStore:
    """Persistence layer for configuration versions.
    
    Provides save and retrieval operations for ConfigVersion objects
    using TimescaleDB as the backing store.
    
    Feature: trading-pipeline-integration
    Requirements: 1.6
    """
    
    def __init__(self, pool) -> None:
        """Initialize the store with a database connection pool.
        
        Args:
            pool: asyncpg connection pool
        """
        self._pool = pool
    
    async def save(self, config: ConfigVersion) -> None:
        """Save a configuration version to the database.
        
        If a version with the same version_id already exists, it will be updated.
        
        Feature: trading-pipeline-integration
        Requirements: 1.6
        
        Args:
            config: ConfigVersion to save
        """
        query = """
            INSERT INTO config_versions 
            (version_id, created_at, created_by, config_hash, parameters, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (version_id) DO UPDATE SET
            created_at = EXCLUDED.created_at,
            created_by = EXCLUDED.created_by,
            config_hash = EXCLUDED.config_hash,
            parameters = EXCLUDED.parameters
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                query,
                config.version_id,
                config.created_at,
                config.created_by,
                config.config_hash,
                json.dumps(config.parameters),
                False,  # is_active defaults to False
            )
    
    async def get_latest(self, created_by: Optional[str] = None) -> Optional[ConfigVersion]:
        """Get the most recent configuration version.
        
        Feature: trading-pipeline-integration
        Requirements: 1.6
        
        Args:
            created_by: Optional filter by source ("live", "backtest", "optimizer")
            
        Returns:
            Most recent ConfigVersion or None if no versions exist
        """
        if created_by:
            query = """
                SELECT version_id, created_at, created_by, config_hash, parameters
                FROM config_versions
                WHERE created_by = $1
                ORDER BY created_at DESC
                LIMIT 1
            """
            params = [created_by]
        else:
            query = """
                SELECT version_id, created_at, created_by, config_hash, parameters
                FROM config_versions
                ORDER BY created_at DESC
                LIMIT 1
            """
            params = []
        
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            if not row:
                return None
            
            return self._row_to_config_version(row)
    
    async def get_by_id(self, version_id: str) -> Optional[ConfigVersion]:
        """Get a configuration version by its ID.
        
        Args:
            version_id: The version ID to look up
            
        Returns:
            ConfigVersion if found, None otherwise
        """
        query = """
            SELECT version_id, created_at, created_by, config_hash, parameters
            FROM config_versions
            WHERE version_id = $1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, version_id)
            if not row:
                return None
            
            return self._row_to_config_version(row)
    
    async def get_by_hash(self, config_hash: str) -> Optional[ConfigVersion]:
        """Get a configuration version by its hash.
        
        Useful for finding if an identical configuration already exists.
        
        Args:
            config_hash: The configuration hash to look up
            
        Returns:
            ConfigVersion if found, None otherwise
        """
        query = """
            SELECT version_id, created_at, created_by, config_hash, parameters
            FROM config_versions
            WHERE config_hash = $1
            ORDER BY created_at DESC
            LIMIT 1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, config_hash)
            if not row:
                return None
            
            return self._row_to_config_version(row)
    
    async def get_active(self) -> Optional[ConfigVersion]:
        """Get the currently active configuration version.
        
        Returns:
            Active ConfigVersion or None if no active version exists
        """
        query = """
            SELECT version_id, created_at, created_by, config_hash, parameters
            FROM config_versions
            WHERE is_active = TRUE
            LIMIT 1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query)
            if not row:
                return None
            
            return self._row_to_config_version(row)
    
    async def set_active(self, version_id: str) -> bool:
        """Set a configuration version as the active version.
        
        This will deactivate any previously active version.
        
        Args:
            version_id: The version ID to set as active
            
        Returns:
            True if the version was found and activated, False otherwise
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # First, deactivate all versions
                await conn.execute(
                    "UPDATE config_versions SET is_active = FALSE WHERE is_active = TRUE"
                )
                
                # Then activate the specified version
                result = await conn.execute(
                    "UPDATE config_versions SET is_active = TRUE WHERE version_id = $1",
                    version_id
                )
                
                # Check if any row was updated
                return result == "UPDATE 1"
    
    async def list_versions(
        self,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConfigVersion]:
        """List configuration versions with optional filtering.
        
        Args:
            created_by: Optional filter by source
            limit: Maximum number of versions to return
            offset: Number of versions to skip
            
        Returns:
            List of ConfigVersion objects ordered by created_at descending
        """
        if created_by:
            query = """
                SELECT version_id, created_at, created_by, config_hash, parameters
                FROM config_versions
                WHERE created_by = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """
            params = [created_by, limit, offset]
        else:
            query = """
                SELECT version_id, created_at, created_by, config_hash, parameters
                FROM config_versions
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
            """
            params = [limit, offset]
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_config_version(row) for row in rows]
    
    async def count_versions(self, created_by: Optional[str] = None) -> int:
        """Count configuration versions with optional filtering.
        
        Args:
            created_by: Optional filter by source
            
        Returns:
            Number of matching versions
        """
        if created_by:
            query = "SELECT COUNT(*) FROM config_versions WHERE created_by = $1"
            params = [created_by]
        else:
            query = "SELECT COUNT(*) FROM config_versions"
            params = []
        
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *params)
    
    async def delete_version(self, version_id: str) -> bool:
        """Delete a configuration version.
        
        Args:
            version_id: The version ID to delete
            
        Returns:
            True if the version was found and deleted, False otherwise
        """
        query = "DELETE FROM config_versions WHERE version_id = $1"
        async with self._pool.acquire() as conn:
            result = await conn.execute(query, version_id)
            return result == "DELETE 1"
    
    def _row_to_config_version(self, row) -> ConfigVersion:
        """Convert a database row to a ConfigVersion object.
        
        Args:
            row: Database row from asyncpg
            
        Returns:
            ConfigVersion instance
        """
        # Parse parameters - handle both dict and string
        parameters = row["parameters"]
        if isinstance(parameters, str):
            try:
                parameters = json.loads(parameters)
            except (json.JSONDecodeError, TypeError):
                parameters = {}
        elif parameters is None:
            parameters = {}
        
        # Ensure created_at has timezone info
        created_at = row["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        
        return ConfigVersion(
            version_id=str(row["version_id"]),
            created_at=created_at,
            created_by=row["created_by"],
            config_hash=row["config_hash"],
            parameters=parameters,
        )
