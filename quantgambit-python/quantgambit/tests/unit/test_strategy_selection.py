import os


class _Dummy:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Spec:
    def __init__(self, strategy_ids):
        self.strategy_ids = strategy_ids
        self.risk = None
        self.conditions = None
        self.strategy_params = {}


class _ProfileRegistry:
    def __init__(self, spec):
        self._spec = spec

    def get_spec(self, profile_id):
        if isinstance(self._spec, dict):
            return self._spec.get(profile_id)
        return self._spec


class _Strategy:
    def __init__(self, strategy_id, should_signal: bool, candidate=None):
        self.strategy_id = strategy_id
        self._should_signal = should_signal
        self._candidate = candidate

    def generate_signal(self, _features, _account, _profile, _params):
        if not self._should_signal:
            return None
        # Dict signal is supported downstream by CandidateGenerationStage.
        return {"side": "long", "strategy_id": self.strategy_id, "meta_reason": "unit_test"}

    def generate_candidate(self, _features, _account, _profile, _params):
        return self._candidate


class _Candidate:
    def __init__(
        self,
        side="long",
        flow_direction_required="positive",
        max_adverse_trend_bias=0.5,
        requires_flow_reversal=True,
    ):
        self.side = side
        self.strategy_id = "mean_reversion_fade"
        self.profile_id = "range_market_scalp"
        self.entry_price = 100.0
        self.sl_price = 99.0 if side == "long" else 101.0
        self.tp_price = 101.0 if side == "long" else 99.0
        self.flow_direction_required = flow_direction_required
        self.max_adverse_trend_bias = max_adverse_trend_bias
        self.requires_flow_reversal = requires_flow_reversal

    def normalize(self, _mid_price):
        return self

    def to_strategy_signal(self, size, confirmation_reason):
        return {
            "side": self.side,
            "strategy_id": self.strategy_id,
            "entry_price": self.entry_price,
            "stop_loss": self.sl_price,
            "take_profit": self.tp_price,
            "size": size,
            "meta_reason": confirmation_reason,
        }


def _mk_registry(
    monkeypatch,
    strategy_ids,
    disabled_strategies="",
    disabled_mean_rev_symbols="",
    enabled_by_symbol="",
):
    from quantgambit.strategies.registry import DeepTraderStrategyRegistry

    monkeypatch.setenv("DISABLE_STRATEGIES", disabled_strategies)
    monkeypatch.setenv("DISABLE_MEAN_REVERSION_SYMBOLS", disabled_mean_rev_symbols)
    monkeypatch.setenv("ENABLE_STRATEGIES_BY_SYMBOL", enabled_by_symbol)

    reg = DeepTraderStrategyRegistry()
    # Override registry internals with cheap stubs so the test is fast/deterministic.
    reg._strategies = {
        sid: _Strategy(sid, should_signal=(sid != "mean_reversion_fade"))
        for sid in strategy_ids
    }
    reg._profile_registry = _ProfileRegistry(_Spec(strategy_ids))
    reg._types = {
        "Features": _Dummy,
        "AccountState": _Dummy,
        "Profile": _Dummy,
        "StrategySignal": _Dummy,
    }
    return reg


def _mk_registry_with_profile_map(monkeypatch, profile_strategy_map):
    from quantgambit.strategies.registry import DeepTraderStrategyRegistry

    monkeypatch.setenv("DISABLE_STRATEGIES", "")
    monkeypatch.setenv("DISABLE_MEAN_REVERSION_SYMBOLS", "")
    monkeypatch.setenv("ENABLE_STRATEGIES_BY_SYMBOL", "")

    reg = DeepTraderStrategyRegistry()
    strategy_ids = sorted({sid for ids in profile_strategy_map.values() for sid in ids})
    reg._strategies = {
        sid: _Strategy(
            sid,
            should_signal=(sid != "amt_value_area_rejection_scalp"),
        )
        for sid in strategy_ids
    }
    reg._profile_registry = _ProfileRegistry(
        {pid: _Spec(ids) for pid, ids in profile_strategy_map.items()}
    )
    reg._types = {
        "Features": _Dummy,
        "AccountState": _Dummy,
        "Profile": _Dummy,
        "StrategySignal": _Dummy,
    }
    return reg


def test_strategy_fallback_skips_disabled_strategy(monkeypatch):
    reg = _mk_registry(
        monkeypatch,
        strategy_ids=["mean_reversion_fade", "low_vol_grind"],
        disabled_strategies="mean_reversion_fade",
        disabled_mean_rev_symbols="",
    )

    features = {"price": 100.0, "spread_bps": 1.0, "timestamp": 123.0}
    market_context = {"session": "us"}
    account = {"equity": 10000.0}

    signal = reg.generate_signal_with_context(
        symbol="BTCUSDT",
        profile_id="range_market_scalp",
        features=features,
        market_context=market_context,
        account=account,
    )

    assert isinstance(signal, dict)
    assert signal["strategy_id"] == "low_vol_grind"


def test_strategy_fallback_skips_mean_reversion_for_symbol(monkeypatch):
    reg = _mk_registry(
        monkeypatch,
        strategy_ids=["mean_reversion_fade", "breakout_scalp"],
        disabled_strategies="",
        disabled_mean_rev_symbols="BTCUSDT",
    )

    features = {"price": 100.0, "spread_bps": 1.0, "timestamp": 123.0}
    market_context = {"session": "us"}
    account = {"equity": 10000.0}

    signal = reg.generate_signal_with_context(
        symbol="BTCUSDT",
        profile_id="range_market_scalp",
        features=features,
        market_context=market_context,
        account=account,
    )

    assert isinstance(signal, dict)
    assert signal["strategy_id"] == "breakout_scalp"


def test_strategy_fallback_allows_symbol_override_for_mean_reversion(monkeypatch):
    reg = _mk_registry(
        monkeypatch,
        strategy_ids=["poc_magnet_scalp", "low_vol_grind"],
        disabled_strategies="",
        disabled_mean_rev_symbols="BTCUSDT",
        enabled_by_symbol="BTCUSDT:poc_magnet_scalp",
    )

    features = {"price": 100.0, "spread_bps": 1.0, "timestamp": 123.0}
    market_context = {"session": "us"}
    account = {"equity": 10000.0}

    signal = reg.generate_signal_with_context(
        symbol="BTCUSDT",
        profile_id="range_market_scalp",
        features=features,
        market_context=market_context,
        account=account,
    )

    assert isinstance(signal, dict)
    assert signal["strategy_id"] == "poc_magnet_scalp"


def test_candidate_confirmation_rejects_and_falls_back(monkeypatch):
    from quantgambit.strategies.registry import DeepTraderStrategyRegistry

    monkeypatch.setenv("ENABLE_CANDIDATE_CONFIRMATION", "true")
    reg = DeepTraderStrategyRegistry()
    reg._strategies = {
        "mean_reversion_fade": _Strategy(
            "mean_reversion_fade",
            should_signal=False,
            candidate=_Candidate(side="long", flow_direction_required="positive"),
        ),
        "low_vol_grind": _Strategy("low_vol_grind", should_signal=True),
    }
    reg._profile_registry = _ProfileRegistry(_Spec(["mean_reversion_fade", "low_vol_grind"]))
    reg._types = {
        "Features": _Dummy,
        "AccountState": _Dummy,
        "Profile": _Dummy,
        "StrategySignal": _Dummy,
    }

    signal = reg.generate_signal_with_context(
        symbol="BTCUSDT",
        profile_id="range_market_scalp",
        features={"price": 100.0, "spread_bps": 1.0, "timestamp": 123.0},
        market_context={"session": "us", "flow_rotation": -0.8, "trend_bias": 0.0},
        account={"equity": 10000.0},
    )

    assert isinstance(signal, dict)
    assert signal["strategy_id"] == "low_vol_grind"


def test_candidate_confirmation_builds_signal_when_strategy_signal_missing(monkeypatch):
    from quantgambit.strategies.registry import DeepTraderStrategyRegistry

    monkeypatch.setenv("ENABLE_CANDIDATE_CONFIRMATION", "true")
    monkeypatch.delenv("DISABLE_STRATEGIES", raising=False)
    monkeypatch.delenv("DISABLE_MEAN_REVERSION_SYMBOLS", raising=False)
    monkeypatch.delenv("ENABLE_STRATEGIES_BY_SYMBOL", raising=False)
    reg = DeepTraderStrategyRegistry()
    reg._strategies = {
        "mean_reversion_fade": _Strategy(
            "mean_reversion_fade",
            should_signal=False,
            candidate=_Candidate(side="long", flow_direction_required="positive"),
        ),
    }
    reg._profile_registry = _ProfileRegistry(_Spec(["mean_reversion_fade"]))
    reg._types = {
        "Features": _Dummy,
        "AccountState": _Dummy,
        "Profile": _Dummy,
        "StrategySignal": _Dummy,
    }

    signal = reg.generate_signal_with_context(
        symbol="BTCUSDT",
        profile_id="range_market_scalp",
        features={"price": 100.0, "spread_bps": 1.0, "timestamp": 123.0},
        market_context={"session": "us", "flow_rotation": 1.2, "trend_bias": 0.1},
        account={"equity": 10000.0},
    )

    assert isinstance(signal, dict)
    assert signal["strategy_id"] == "mean_reversion_fade"
    assert signal["side"] == "long"
    assert signal["size"] > 0
    assert "candidate_confirmed" in signal["meta_reason"]


def test_profile_fallback_uses_next_eligible_profile(monkeypatch):
    monkeypatch.setenv("PROFILE_SIGNAL_FALLBACK_MAX_PROFILES", "2")
    monkeypatch.delenv("DISABLE_STRATEGIES", raising=False)
    monkeypatch.delenv("DISABLE_MEAN_REVERSION_SYMBOLS", raising=False)
    monkeypatch.delenv("ENABLE_STRATEGIES_BY_SYMBOL", raising=False)
    reg = _mk_registry_with_profile_map(
        monkeypatch,
        {
            "value_area_rejection": ["amt_value_area_rejection_scalp"],
            "near_poc_micro_scalp": ["poc_magnet_scalp"],
        },
    )

    features = {
        "price": 100.0,
        "spread_bps": 1.0,
        "timestamp": 123.0,
        "profile_scores": [
            {"profile_id": "value_area_rejection", "eligible": True, "score": 0.91},
            {"profile_id": "near_poc_micro_scalp", "eligible": True, "score": 0.86},
        ],
    }
    market_context = {"session": "us"}
    account = {"equity": 10000.0}

    signal = reg.generate_signal_with_context(
        symbol="ETHUSDT",
        profile_id="value_area_rejection",
        features=features,
        market_context=market_context,
        account=account,
    )

    assert isinstance(signal, dict)
    assert signal["strategy_id"] == "poc_magnet_scalp"
    assert signal["profile_id"] == "near_poc_micro_scalp"


def test_profile_attempts_prefer_router_top_score_over_stale_profile_id(monkeypatch):
    monkeypatch.setenv("PROFILE_SIGNAL_FALLBACK_MAX_PROFILES", "2")
    monkeypatch.delenv("DISABLE_STRATEGIES", raising=False)
    monkeypatch.delenv("DISABLE_MEAN_REVERSION_SYMBOLS", raising=False)
    monkeypatch.delenv("ENABLE_STRATEGIES_BY_SYMBOL", raising=False)
    reg = _mk_registry_with_profile_map(
        monkeypatch,
        {
            "poc_magnet_profile": ["poc_magnet_scalp"],
            "range_market_scalp": ["mean_reversion_fade"],
        },
    )

    features = {
        "price": 100.0,
        "spread_bps": 1.0,
        "timestamp": 123.0,
        "profile_scores": [
            {"profile_id": "range_market_scalp", "eligible": True, "score": 0.91},
            {"profile_id": "poc_magnet_profile", "eligible": True, "score": 0.90},
        ],
    }
    market_context = {"session": "us"}
    account = {"equity": 10000.0}

    signal = reg.generate_signal_with_context(
        symbol="ETHUSDT",
        profile_id="poc_magnet_profile",
        features=features,
        market_context=market_context,
        account=account,
    )

    assert isinstance(signal, dict)
    assert signal["strategy_id"] == "mean_reversion_fade"
    assert signal["profile_id"] == "range_market_scalp"
