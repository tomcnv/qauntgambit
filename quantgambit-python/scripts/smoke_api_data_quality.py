import os
from pathlib import Path
from fastapi.testclient import TestClient


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def summarize(label: str, payload):
    if isinstance(payload, dict):
        if 'count' in payload:
            print(f"{label}: count={payload.get('count')}")
            return
        if 'data' in payload and isinstance(payload.get('data'), list):
            print(f"{label}: data={len(payload.get('data'))}")
            return
        if 'metrics' in payload and isinstance(payload.get('metrics'), list):
            print(f"{label}: metrics={len(payload.get('metrics'))}")
            return
        if 'alerts' in payload and isinstance(payload.get('alerts'), list):
            print(f"{label}: alerts={len(payload.get('alerts'))}")
            return
    print(f"{label}: ok")


def main() -> None:
    load_env(Path(__file__).resolve().parents[1] / '.env')
    from quantgambit.api.app import app

    client = TestClient(app)
    endpoints = [
        ("/api/data-quality/metrics", {"limit": 50}),
        ("/api/data-quality/metrics/timeseries", {"limit": 50}),
        ("/api/data-quality/health", {}),
        ("/api/data-quality/gaps", {"limit": 50}),
        ("/api/data-quality/alerts", {"limit": 50}),
        ("/api/risk/exposure", {}),
        ("/api/risk/metrics", {"limit": 50}),
    ]
    failures = False
    for path, params in endpoints:
        try:
            resp = client.get(path, params=params)
        except Exception as exc:
            failures = True
            print(f"{path}: error {exc}")
            continue
        if resp.status_code != 200:
            failures = True
            print(f"{path}: status={resp.status_code} body={resp.text[:200]}")
            continue
        try:
            data = resp.json()
        except Exception:
            failures = True
            print(f"{path}: invalid_json")
            continue
        summarize(path, data)
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
