"""Configuration registry for trading pipeline integration.

This module provides the central ConfigurationRegistry that ensures parity
between live trading and backtest systems by maintaining a single source
of truth for all configuration parameters.

Feature: trading-pipeline-integration
Requirements: 1.1 - THE System SHALL maintain a single source of truth for all trading
              configuration parameters
              1.2 - WHEN a backtest is initiated THEN the System SHALL automatically load
              the current live configuration unless explicitly overridden
              1.5 - WHEN critical configuration parameters differ THEN the System SHALL
              require explicit acknowledgment before proceeding
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from quantgambit.integration.config_version import ConfigVersion, ConfigVersionStore
from quantgambit.integration.config_diff import ConfigDiff, ConfigDiffEngine


class ConfigurationError(Exception):
    """Exception raised when configuration parity requirements are violated.
    
    This exception is raised when critical configuration parameters differ
    between live and backtest configurations and require_parity is True.
    
    Feature: trading-pipeline-integration
    Requirements: 1.5
    
    Attributes:
        message: Human-readable error message
        critical_diffs: List of critical parameter differences
        diff: The full ConfigDiff object if available
    """
    
    def __init__(
        self,
        message: str,
        critical_diffs: Optional[list] = None,
        diff: Optional[ConfigDiff] = None,
    ) -> None:
        """Initialize ConfigurationError.
        
        Args:
            message: Human-readable error message
            critical_diffs: List of critical parameter differences
            diff: The full ConfigDiff object if available
        """
        super().__init__(message)
        self.message = message
        self.critical_diffs = critical_diffs or []
        self.diff = diff
    
    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.critical_diffs:
            diffs_str = ", ".join(
                f"{key}: {old!r} -> {new!r}"
                for key, old, new in self.critical_diffs
            )
            return f"{self.message}: [{diffs_str}]"
        return self.message


class ConfigurationRegistry:
    """Central configuration management with versioning and parity enforcement.
    
    The ConfigurationRegistry serves as the single source of truth for all
    trading configuration parameters. It ensures that both live trading and
    backtest systems use consistent configurations, with support for:
    
    - Loading the current live configuration
    - Creating backtest configurations with optional overrides
    - Enforcing parity between live and backtest configurations
    - Versioning all configuration changes
    
    Feature: trading-pipeline-integration
    Requirements: 1.1, 1.2, 1.5
    
    Example:
        >>> registry = ConfigurationRegistry(pool, redis)
        >>> live_config = await registry.get_live_config()
        >>> backtest_config, diff = await registry.get_config_for_backtest(
        ...     override_params={"slippage_bps": 2.0},
        ...     require_parity=False,
        ... )
    """
    
    def __init__(self, timescale_pool, redis_client) -> None:
        """Initialize the ConfigurationRegistry.
        
        Args:
            timescale_pool: asyncpg connection pool for TimescaleDB
            redis_client: Redis client for caching (optional, can be None)
        """
        self._pool = timescale_pool
        self._redis = redis_client
        self._version_store = ConfigVersionStore(timescale_pool)
        self._diff_engine = ConfigDiffEngine()
    
    async def get_live_config(self) -> ConfigVersion:
        """Get current live configuration.
        
        Retrieves the most recent configuration version created by the live
        trading system. If no live configuration exists, creates and saves
        a default empty configuration.
        
        Feature: trading-pipeline-integration
        Requirements: 1.1
        
        Returns:
            The current live ConfigVersion
            
        Raises:
            ConfigurationError: If no live configuration exists and strict mode
        """
        # First try to get the active configuration
        config = await self._version_store.get_active()
        if config is not None:
            return config
        
        # Fall back to the latest live configuration
        config = await self._version_store.get_latest("live")
        if config is not None:
            return config
        
        # If no live config exists, create a default empty one and save it
        # This allows the system to bootstrap without pre-existing config
        # and ensures the config_version foreign key constraint is satisfied
        default_config = ConfigVersion.create(
            version_id=f"default_{uuid4().hex[:8]}",
            created_by="live",
            parameters={},
        )
        
        # Save the default config to satisfy foreign key constraints
        try:
            await self._version_store.save(default_config)
        except Exception:
            # If save fails (e.g., duplicate), try to get the latest again
            config = await self._version_store.get_latest("live")
            if config is not None:
                return config
        
        return default_config
    
    async def get_config_for_backtest(
        self,
        override_params: Optional[Dict[str, Any]] = None,
        require_parity: bool = True,
    ) -> Tuple[ConfigVersion, Optional[ConfigDiff]]:
        """Get configuration for backtest with optional overrides.
        
        Loads the current live configuration and optionally applies parameter
        overrides for the backtest. When require_parity is True, raises an
        error if critical parameters differ between live and backtest configs.
        
        Feature: trading-pipeline-integration
        Requirements: 1.2, 1.5
        
        Args:
            override_params: Parameters to override from live config. If None,
                           the exact live configuration is used.
            require_parity: If True, raise ConfigurationError when critical
                          parameters differ. Defaults to True.
            
        Returns:
            Tuple of (backtest_config, diff_from_live). The diff is None if
            no overrides were specified.
            
        Raises:
            ConfigurationError: If require_parity is True and critical
                              configuration parameters differ.
        """
        live_config = await self.get_live_config()
        
        if override_params:
            # Merge live parameters with overrides
            backtest_params = {**live_config.parameters, **override_params}
            
            # Create a new backtest configuration version
            backtest_config = ConfigVersion(
                version_id=f"backtest_{uuid4().hex[:8]}",
                created_at=datetime.now(timezone.utc),
                created_by="backtest",
                config_hash=self._hash_params(backtest_params),
                parameters=backtest_params,
            )
            
            # Compute the diff between live and backtest configs
            diff = self._diff_engine.compare(live_config, backtest_config)
            
            # Enforce parity if required
            if require_parity and diff.has_critical_diffs:
                raise ConfigurationError(
                    "Critical configuration differences detected",
                    critical_diffs=diff.critical_diffs,
                    diff=diff,
                )
            
            return backtest_config, diff
        
        # No overrides - use live config directly
        return live_config, None
    
    async def save_version(self, config: ConfigVersion) -> None:
        """Save configuration version to database.
        
        Persists a configuration version to TimescaleDB for historical
        tracking and retrieval.
        
        Feature: trading-pipeline-integration
        Requirements: 1.6
        
        Args:
            config: ConfigVersion to save
        """
        await self._version_store.save(config)
    
    async def get_version(self, version_id: str) -> Optional[ConfigVersion]:
        """Get a specific configuration version by ID.
        
        Args:
            version_id: The version ID to retrieve
            
        Returns:
            ConfigVersion if found, None otherwise
        """
        return await self._version_store.get_by_id(version_id)
    
    async def set_active_config(self, version_id: str) -> bool:
        """Set a configuration version as the active live configuration.
        
        Args:
            version_id: The version ID to set as active
            
        Returns:
            True if the version was found and activated, False otherwise
        """
        return await self._version_store.set_active(version_id)
    
    async def create_and_save_config(
        self,
        parameters: Dict[str, Any],
        created_by: str = "live",
        set_active: bool = False,
    ) -> ConfigVersion:
        """Create a new configuration version and save it.
        
        Convenience method that creates a new ConfigVersion with the given
        parameters, saves it to the database, and optionally sets it as active.
        
        Args:
            parameters: Configuration parameters dictionary
            created_by: Source of the configuration ("live", "backtest", "optimizer")
            set_active: If True, set this version as the active configuration
            
        Returns:
            The created ConfigVersion
        """
        config = ConfigVersion.create(
            version_id=f"{created_by}_{uuid4().hex[:8]}",
            created_by=created_by,
            parameters=parameters,
        )
        
        await self.save_version(config)
        
        if set_active:
            await self.set_active_config(config.version_id)
        
        return config
    
    def compare_configs(
        self,
        source: ConfigVersion,
        target: ConfigVersion,
    ) -> ConfigDiff:
        """Compare two configuration versions.
        
        Computes the diff between two configurations, categorizing all
        differences as critical, warning, or info.
        
        Args:
            source: The source configuration (typically live)
            target: The target configuration (typically backtest)
            
        Returns:
            ConfigDiff with all differences categorized
        """
        return self._diff_engine.compare(source, target)
    
    def _hash_params(self, params: Dict[str, Any]) -> str:
        """Create deterministic hash of parameters.
        
        Generates a 16-character hex hash of the configuration parameters
        for quick comparison and deduplication.
        
        Args:
            params: Configuration parameters dictionary
            
        Returns:
            16-character hex hash string
        """
        # Sort keys and use default=str for non-serializable types
        serialized = json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]
