from quantgambit.config.loss_prevention import load_ev_gate_config


def test_load_ev_gate_side_and_symbol_side_thresholds(monkeypatch):
    monkeypatch.setenv("EV_GATE_MIN_EXPECTED_EDGE_BPS", "10")
    monkeypatch.setenv("EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SIDE", "long:14,short:22")
    monkeypatch.setenv(
        "EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SYMBOL_SIDE",
        "BTCUSDT:short:30,ETHUSDT:long:16",
    )

    cfg = load_ev_gate_config()

    assert cfg.min_expected_edge_bps == 10.0
    assert cfg.min_expected_edge_bps_by_side["long"] == 14.0
    assert cfg.min_expected_edge_bps_by_side["short"] == 22.0
    assert cfg.min_expected_edge_bps_by_symbol_side["BTCUSDT:short"] == 30.0
    assert cfg.min_expected_edge_bps_by_symbol_side["ETHUSDT:long"] == 16.0
