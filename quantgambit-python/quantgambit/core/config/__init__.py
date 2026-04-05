"""
Configuration management module.

Provides:
- ConfigBundle: Versioned configuration snapshot
- ConfigBundleManager: Bundle lifecycle management
- RiskProfile: Risk parameter profiles
- BundleStore: Storage interface
"""

from quantgambit.core.config.audit import (
    AuditEntry,
    BundleStatus,
    ConfigBundle,
    ConfigBundleManager,
)
from quantgambit.core.config.profiles import (
    AGGRESSIVE_PROFILE,
    BALANCED_PROFILE,
    CONSERVATIVE_PROFILE,
    RiskProfile,
    SCALPER_PROFILE,
)
from quantgambit.core.config.store import InMemoryBundleStore

__all__ = [
    # Audit
    "AuditEntry",
    "BundleStatus",
    "ConfigBundle",
    "ConfigBundleManager",
    # Profiles
    "RiskProfile",
    "CONSERVATIVE_PROFILE",
    "BALANCED_PROFILE",
    "AGGRESSIVE_PROFILE",
    "SCALPER_PROFILE",
    # Store
    "InMemoryBundleStore",
]
