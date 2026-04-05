import pytest

from quantgambit.signals.stages.candidate_generation import CandidateGenerationStage


class _Snapshot:
    def __init__(self, data_quality_score: float, spread_bps: float, vol_shock: bool):
        self.data_quality_score = data_quality_score
        self.spread_bps = spread_bps
        self.vol_shock = vol_shock


def test_candidate_confidence_prefers_prediction_confidence_when_signal_missing():
    stage = CandidateGenerationStage()
    snapshot = _Snapshot(data_quality_score=1.0, spread_bps=2.0, vol_shock=False)

    confidence = stage._calculate_confidence(
        signal={"side": "long"},
        snapshot=snapshot,
        prediction={"confidence": 0.72},
    )

    # 0.72 base from prediction, then tight spread boost x1.1
    assert confidence == pytest.approx(0.792, rel=1e-6)


def test_candidate_confidence_blends_prediction_and_signal_confidence():
    stage = CandidateGenerationStage()
    snapshot = _Snapshot(data_quality_score=1.0, spread_bps=2.0, vol_shock=False)

    confidence = stage._calculate_confidence(
        signal={"side": "long", "confidence": 0.40},
        snapshot=snapshot,
        prediction={"confidence": 0.70},
    )

    # Blend = 0.7*0.70 + 0.3*0.40 = 0.61, then tight spread boost x1.1
    assert confidence == pytest.approx(0.671, rel=1e-6)
