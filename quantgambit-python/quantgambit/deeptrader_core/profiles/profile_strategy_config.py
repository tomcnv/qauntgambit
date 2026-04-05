"""
DEPRECATED: Profile Strategy Configuration

This file is deprecated and replaced by the Chessboard profile system.

OLD SYSTEM (78 profiles):
- Hard-coded profile_id -> strategy mappings
- No lifecycle management
- No performance tracking
- Redundant configurations

NEW SYSTEM (20 orthogonal profiles):
- ProfileSpec definitions in core/strategies/chessboard/canonical_profiles.py
- ProfileRouter for context-aware selection
- ProfileRegistry for lifecycle management
- ProfileInstance for performance tracking

For backward compatibility with test scripts, we provide a minimal stub.
"""

from typing import Dict, Any

# Minimal stub for backward compatibility
# Maps old profile IDs to new Chessboard profile IDs
PROFILE_STRATEGY_CONFIG: Dict[str, Dict[str, Any]] = {}

# Migration mapping (for reference only)
MIGRATION_MAP = {
    # Old pattern -> New orthogonal profile
    "flat_inside_low_*_normal": "poc_magnet_profile",
    "flat_inside_low_*_compression": "spread_compression_profile",
    "flat_inside_normal_*_*": "vwap_reversion_profile",
    "*_above_*_*_normal": "value_area_rejection",
    "*_below_*_*_normal": "value_area_rejection",
    "*_inside_*_*_normal": "poc_magnet_profile",
    "up_*_*_*_normal": "trend_pullback_profile",
    "down_*_*_*_normal": "trend_pullback_profile",
    "*_inside_normal_*_normal": "trend_pullback_profile",
    "*_*_high_*_normal": "high_vol_breakout_profile",
    "*_*_high_*_*": "high_vol_breakout_profile",
    "*_*_normal_us_normal_orb": "opening_range_breakout_profile",
    "*_*_normal_europe_normal_orb": "opening_range_breakout_profile",
    "*_*_normal_asia_normal_orb": "opening_range_breakout_profile",
    "*_*_*_*_normal_hunt": "liquidity_hunt_profile",
    "*_*_*_*_vwap": "vwap_reversion_profile",
    "*_*_low_*_compression": "spread_compression_profile",
    "*_*_*_*_normal_expansion": "vol_expansion_profile",
}


def get_profile_config(profile_id: str) -> Dict[str, Any]:
    """
    DEPRECATED: Use ProfileRouter.select_profiles() instead
    
    This function is kept for backward compatibility with test scripts.
    """
    print(f"⚠️  WARNING: get_profile_config() is deprecated. Use ProfileRouter instead.")
    print(f"   Old profile: {profile_id}")
    print(f"   New system: core/strategies/chessboard/canonical_profiles.py")
    return {}


# For scripts that check profile count
def get_profile_count() -> int:
    """Return the count of Chessboard profiles (20)"""
    from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import ALL_CANONICAL_PROFILES
    return len(ALL_CANONICAL_PROFILES)


if __name__ == "__main__":
    print("=" * 70)
    print("PROFILE SYSTEM MIGRATION")
    print("=" * 70)
    print(f"Old system: 78 profiles (DEPRECATED)")
    print(f"New system: {get_profile_count()} Chessboard profiles (ACTIVE)")
    print()
    print("To use the new system:")
    print("  from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry")
    print("  from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter")
    print()
    print("See: CHESSBOARD_MIGRATION_PLAN.md")
    print("=" * 70)
