from quantgambit.runtime.entrypoint import _is_external_source


def test_external_source_true_with_source():
    env = {"ORDERBOOK_SOURCE": "external"}
    assert _is_external_source("ORDERBOOK_SOURCE", "ORDERBOOK_EXTERNAL", env_override=env) is True


def test_external_source_true_with_flag():
    env = {"ORDERBOOK_SOURCE": "", "ORDERBOOK_EXTERNAL": "true"}
    assert _is_external_source("ORDERBOOK_SOURCE", "ORDERBOOK_EXTERNAL", env_override=env) is True


def test_external_source_false_default():
    env = {"ORDERBOOK_SOURCE": "", "ORDERBOOK_EXTERNAL": "false"}
    assert _is_external_source("ORDERBOOK_SOURCE", "ORDERBOOK_EXTERNAL", env_override=env) is False
