from pathlib import Path

from quantgambit.config.env_loading import load_layered_env_defaults


def test_runtime_live_layering_matches_backend_contract(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DB_HOST=base-host\nJWT_SECRET=base-secret\nPREDICTION_ONNX_MIN_MARGIN=0.10\n")
    (tmp_path / ".env.runtime-live").write_text("PREDICTION_ONNX_MIN_MARGIN=0.005\nJWT_SECRET=live-secret\n")

    merged, _ = load_layered_env_defaults(tmp_path, ".env.runtime-live")

    assert merged["DB_HOST"] == "base-host"
    assert merged["JWT_SECRET"] == "live-secret"
    assert merged["PREDICTION_ONNX_MIN_MARGIN"] == "0.005"
