"""Helpers for deterministic layered environment-file loading."""

from __future__ import annotations

from pathlib import Path
from typing import MutableMapping


def _parse_env_lines(raw_text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key] = value
    return values


def read_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    try:
        from dotenv import dotenv_values  # type: ignore

        parsed = dotenv_values(env_path)
        return {str(key): str(value) for key, value in parsed.items() if value is not None}
    except Exception:
        return _parse_env_lines(env_path.read_text())


def resolve_env_file(project_root: Path, env_file: str | None) -> Path | None:
    if not env_file:
        return None
    candidate = Path(env_file)
    if candidate.is_file():
        return candidate
    rooted = project_root / env_file
    return rooted if rooted.is_file() else None


def load_layered_env_defaults(project_root: Path, env_file: str | None = None) -> tuple[dict[str, str], list[Path]]:
    merged: dict[str, str] = {}
    loaded_paths: list[Path] = []

    baseline = project_root / ".env"
    if baseline.is_file():
        merged.update(read_env_file(baseline))
        loaded_paths.append(baseline)

    selected = resolve_env_file(project_root, env_file)
    if selected and selected not in loaded_paths:
        merged.update(read_env_file(selected))
        loaded_paths.append(selected)

    return merged, loaded_paths


def apply_layered_env_defaults(
    project_root: Path,
    env_file: str | None,
    environ: MutableMapping[str, str],
) -> list[Path]:
    merged, loaded_paths = load_layered_env_defaults(project_root, env_file)
    for key, value in merged.items():
        environ.setdefault(key, value)
    return loaded_paths
