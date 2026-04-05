"""
Chessboard Strategy Engine

Formal specifications and lifecycle management for the 20 canonical
market structure patterns described in the DeepTrader white paper.
"""

from .profile_spec import (
    ProfileSpec,
    ProfileConditions,
    ProfileRiskParameters,
    ProfileLifecycle,
    ProfileInstance,
    ProfileLifecycleState,
    ProfileRegistry,
    get_profile_registry
)

__all__ = [
    'ProfileSpec',
    'ProfileConditions',
    'ProfileRiskParameters',
    'ProfileLifecycle',
    'ProfileInstance',
    'ProfileLifecycleState',
    'ProfileRegistry',
    'get_profile_registry',
]

