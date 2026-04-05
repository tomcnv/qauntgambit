from __future__ import annotations

import pytest

from quantgambit.profiles.router import (
    DeepTraderProfileRouter,
    _build_context_vector,
)
from quantgambit.deeptrader_core.profiles.profile_router import _normalize_profile_id_alias


def test_build_context_vector_splits_combined_depth_usd():
    ctx = {
        "session": "europe",
        "hour_utc": 7,
        "price": 68911.3,
        "bid": 68911.3,
        "ask": 68907.3,
        "trend_direction": "flat",
        "trend_strength": 0.0,
        "poc_price": 69158.12,
        "vah_price": 69209.64,
        "val_price": 69069.13,
        "position_in_value": "below",
        "trades_per_second": 2.0,
        "data_quality_score": 1.0,
        "depth_usd": 1296478.79,
    }

    vec = _build_context_vector("BTCUSDT", ctx, {})

    assert vec is not None
    assert vec.bid_depth_usd == pytest.approx(648239.395)
    assert vec.ask_depth_usd == pytest.approx(648239.395)


def test_deeptrader_profile_router_selects_when_only_combined_depth_is_present():
    router = DeepTraderProfileRouter(backtesting_mode=True)
    ctx = {
        "session": "europe",
        "hour_utc": 7,
        "price": 68911.3,
        "bid": 68911.3,
        "ask": 68907.3,
        "trend_direction": "flat",
        "trend_strength": 0.0,
        "poc_price": 69158.12,
        "vah_price": 69209.64,
        "val_price": 69069.13,
        "position_in_value": "below",
        "trades_per_second": 2.0,
        "data_quality_score": 1.0,
        "depth_usd": 1296478.79,
    }

    selected = router.route_with_context("BTCUSDT", ctx, {})

    assert selected is not None
    assert router.last_scores


def test_deeptrader_profile_router_falls_back_to_top_raw_profile_when_policy_filters_all(monkeypatch):
    router = DeepTraderProfileRouter.__new__(DeepTraderProfileRouter)

    class FakeScore:
        def __init__(self, profile_id: str, score: float):
            self.profile_id = profile_id
            self.score = score

    class FakeRouter:
        def select_profiles(self, context_vector, top_k=10, symbol=None):
            return [
                FakeScore("range_market_scalp", 0.82),
                FakeScore("poc_magnet_profile", 0.67),
            ]

    router._router = FakeRouter()
    router._policy = {}
    router.last_scores = []
    router._profile_first_seen = {}
    router._profile_seen_counts = {}
    router._profile_versions = {}

    def _filter_scores(scores, risk_mode, market_context, features):
        router.last_scores = []
        return []

    router._filter_scores = _filter_scores

    ctx = {
        "session": "us",
        "hour_utc": 16,
        "price": 68911.3,
        "bid": 68911.3,
        "ask": 68907.3,
        "trend_direction": "flat",
        "trend_strength": 0.0,
        "poc_price": 69158.12,
        "vah_price": 69209.64,
        "val_price": 69069.13,
        "position_in_value": "below",
        "trades_per_second": 2.0,
        "data_quality_score": 1.0,
        "depth_usd": 1296478.79,
    }

    selected = router.route_with_context("BTCUSDT", ctx, {})

    assert selected == "range_market_scalp"


def test_deeptrader_profile_router_returns_none_when_no_scores_are_available():
    router = DeepTraderProfileRouter.__new__(DeepTraderProfileRouter)

    class FakeRouter:
        def select_profiles(self, context_vector, top_k=10, symbol=None):
            return []

    router._router = FakeRouter()
    router._policy = {}
    router.last_scores = []
    router._profile_first_seen = {}
    router._profile_seen_counts = {}
    router._profile_versions = {}

    ctx = {
        "session": "us",
        "hour_utc": 16,
        "price": 68911.3,
        "bid": 68911.3,
        "ask": 68907.3,
        "trend_direction": "flat",
        "trend_strength": 0.0,
        "poc_price": 69158.12,
        "vah_price": 69209.64,
        "val_price": 69069.13,
        "position_in_value": "below",
        "trades_per_second": 2.0,
        "data_quality_score": 1.0,
        "depth_usd": 1296478.79,
    }

    selected = router.route_with_context("ETHUSDT", ctx, {})

    assert selected is None
    assert router.last_scores == []


def test_normalize_profile_id_alias_strips_profile_suffix():
    assert _normalize_profile_id_alias("poc_magnet_profile") == "poc_magnet"
    assert _normalize_profile_id_alias("value_area_rejection") == "value_area_rejection"
