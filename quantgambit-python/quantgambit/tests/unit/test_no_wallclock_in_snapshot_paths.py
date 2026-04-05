from __future__ import annotations

from pathlib import Path
import re


def test_no_wallclock_in_snapshot_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    denylist = [
        root / "signals" / "feature_worker.py",
        root / "market" / "quality.py",
        root / "market" / "trades.py",
        root / "market" / "derived_metrics.py",
    ]
    banned_patterns = [
        r"time\.time\(",
        r"datetime\.now\(",
        r"Timestamp\.now\(",
    ]
    violations = []
    for path in denylist:
        text = path.read_text()
        for pattern in banned_patterns:
            if re.search(pattern, text):
                violations.append(f"{path}:{pattern}")
    assert not violations, f"wallclock_calls_detected: {violations}"
