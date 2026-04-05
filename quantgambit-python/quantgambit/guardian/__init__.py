"""Guardian module for standalone position monitoring.

Architecture:
- Phase 1: Per-Tenant Guardian (TenantPositionGuardian)
  - One process per tenant
  - Monitors all exchange accounts for that tenant
  
- Phase 2: Pooled Workers
  - Shared worker pool
  - Workers assigned accounts dynamically
  
- Phase 3: Regional Scaling
  - Regional worker pools
  - Exchange-specific optimization
"""

from .standalone_guardian import (
    GuardianConfig,
    StandalonePositionGuardian,
    run_guardian,
)

from .tenant_guardian import (
    TenantGuardianConfig,
    TenantPositionGuardian,
    ExchangeAccountInfo,
    run_tenant_guardian,
)

__all__ = [
    # Standalone (per-account)
    "GuardianConfig",
    "StandalonePositionGuardian", 
    "run_guardian",
    # Per-tenant
    "TenantGuardianConfig",
    "TenantPositionGuardian",
    "ExchangeAccountInfo",
    "run_tenant_guardian",
]

