from __future__ import annotations

from pathlib import Path

from quantgambit.deeptrader_core.profiles.router_config import RouterConfig


def test_router_config_reads_profile_ttl_from_env_file_when_not_in_process_env(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env.runtime-live"
    env_file.write_text("PROFILE_MIN_TTL_SEC=30\n", encoding="utf-8")

    monkeypatch.delenv("PROFILE_MIN_TTL_SEC", raising=False)
    monkeypatch.setenv("ENV_FILE", str(env_file))

    config = RouterConfig()

    assert config.min_profile_ttl_sec == 30.0
