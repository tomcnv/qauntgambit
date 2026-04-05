#!/usr/bin/env python3
import json
import os
import urllib.request


def _get(url: str, token: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8")


def main() -> int:
    base = os.getenv("API_BASE_URL", "http://localhost:8001/api/v1")
    token = os.getenv("AUTH_TOKEN")
    if not token:
        raise SystemExit("AUTH_TOKEN is required")

    status, body = _get(f"{base}/control/state?tenant_id=t1&bot_id=b1", token)
    print("control_state", status, body[:200])

    status, body = _get(f"{base}/backtests/metrics?tenant_id=t1&bot_id=b1&limit=1", token)
    print("backtests_metrics", status, body[:200])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
