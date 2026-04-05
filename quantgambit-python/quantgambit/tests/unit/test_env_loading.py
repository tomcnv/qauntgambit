from pathlib import Path

from quantgambit.config.env_loading import apply_layered_env_defaults, load_layered_env_defaults


def test_load_layered_env_defaults_selected_file_overrides_baseline(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("A=base\nB=base\n")
    (tmp_path / ".env.runtime-live").write_text("B=live\nC=live\n")

    merged, loaded_paths = load_layered_env_defaults(tmp_path, ".env.runtime-live")

    assert merged == {"A": "base", "B": "live", "C": "live"}
    assert loaded_paths == [tmp_path / ".env", tmp_path / ".env.runtime-live"]


def test_apply_layered_env_defaults_preserves_explicit_process_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("A=base\nB=base\n")
    (tmp_path / ".env.spot").write_text("B=spot\nC=spot\n")
    env = {"B": "explicit", "D": "explicit"}

    loaded_paths = apply_layered_env_defaults(tmp_path, ".env.spot", env)

    assert loaded_paths == [tmp_path / ".env", tmp_path / ".env.spot"]
    assert env == {
        "A": "base",
        "B": "explicit",
        "C": "spot",
        "D": "explicit",
    }
