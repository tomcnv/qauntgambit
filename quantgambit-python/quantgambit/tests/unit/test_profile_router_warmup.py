import time

from quantgambit.profiles.router import DeepTraderProfileRouter


class FakeScore:
    def __init__(self, profile_id: str, score: float = 1.0, confidence: float = 1.0):
        self.profile_id = profile_id
        self.score = score
        self.confidence = confidence
        self.reasons = []


def test_profile_router_quarantine_blocks_profile():
    router = DeepTraderProfileRouter()
    router.set_policy({"profile_quarantine_sec": 10})
    router._profile_first_seen["p1"] = time.time()
    router._profile_seen_counts["p1"] = 1
    scores = [FakeScore("p1")]

    eligible = router._filter_scores(scores, None, {}, {})
    assert eligible == []
    assert "profile_quarantine" in router.last_scores[0]["eligibility_reasons"]


def test_profile_router_warmup_requires_samples():
    router = DeepTraderProfileRouter()
    router.set_policy({"profile_warmup_min_samples": 2})
    router._profile_first_seen["p1"] = time.time() - 60
    scores = [FakeScore("p1")]

    eligible_first = router._filter_scores(scores, None, {}, {})
    assert eligible_first == []
    assert "profile_warmup" in router.last_scores[0]["eligibility_reasons"]

    eligible_second = router._filter_scores(scores, None, {}, {})
    assert eligible_second
