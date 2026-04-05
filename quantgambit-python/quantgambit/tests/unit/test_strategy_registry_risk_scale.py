from quantgambit.strategies.registry import _apply_risk_scale


class DummySignal:
    def __init__(self, size):
        self.size = size


def test_apply_risk_scale_dict():
    signal = {"size": 10.0}
    scaled = _apply_risk_scale(signal, {"risk_mode": "conservative", "risk_scale": 0.5})
    assert scaled["size"] == 5.0


def test_apply_risk_scale_object():
    signal = DummySignal(8.0)
    scaled = _apply_risk_scale(signal, {"risk_mode": "conservative", "risk_scale": 0.25})
    assert scaled.size == 2.0


def test_apply_risk_scale_noop():
    signal = {"size": 7.0}
    scaled = _apply_risk_scale(signal, {"risk_mode": "normal", "risk_scale": 0.1})
    assert scaled["size"] == 7.0
