from __future__ import annotations

import ast
from pathlib import Path
import warnings


ROOT = Path(__file__).resolve().parents[2]
TARGET_ROOT = ROOT / "quantgambit"


def _iter_python_files() -> list[Path]:
    return sorted(
        path
        for path in TARGET_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _imported_decision_engine_aliases(tree: ast.AST) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "quantgambit.signals.decision_engine":
            continue
        for imported in node.names:
            if imported.name == "DecisionEngine":
                aliases.add(imported.asname or imported.name)
    aliases.add("DecisionEngine")
    return aliases


def _call_target_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return None


def _has_keyword(node: ast.Call, name: str) -> bool:
    return any(keyword.arg == name for keyword in node.keywords)


def _keyword_is_false(node: ast.Call, name: str) -> bool:
    for keyword in node.keywords:
        if keyword.arg != name:
            continue
        value = keyword.value
        return isinstance(value, ast.Constant) and value.value is False
    return False


def test_non_test_decision_engine_calls_require_explicit_ev_gate_config():
    violations: list[str] = []

    for path in _iter_python_files():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _imported_decision_engine_aliases(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target_name = _call_target_name(node)
            if target_name not in aliases:
                continue
            if _has_keyword(node, "stages"):
                continue
            if _keyword_is_false(node, "use_gating_system"):
                continue
            if _has_keyword(node, "ev_gate_config"):
                continue
            violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert not violations, (
        "DecisionEngine calls in non-test code must pass explicit ev_gate_config "
        "(or use stages=... / use_gating_system=False). Violations:\n- "
        + "\n- ".join(violations)
    )
