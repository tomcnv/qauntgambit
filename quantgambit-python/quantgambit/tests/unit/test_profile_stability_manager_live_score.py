from __future__ import annotations

import time
from types import SimpleNamespace

from quantgambit.deeptrader_core.profiles.profile_stability_manager import ProfileStabilityManager


def test_should_switch_uses_current_live_score_when_cached_score_is_stale():
    manager = ProfileStabilityManager(
        SimpleNamespace(min_profile_ttl_sec=0.0, switch_margin=0.06)
    )
    now = time.time()
    manager.record_selection("BTCUSDT", "poc_magnet_profile", 0.82, current_time=now - 30.0)

    should_switch = manager.should_switch(
        symbol="BTCUSDT",
        new_profile_id="value_area_rejection_profile",
        new_score=0.659,
        current_live_score=0.590,
        current_time=now,
    )

    assert should_switch is True
