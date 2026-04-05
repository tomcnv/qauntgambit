#!/usr/bin/env python3
import os
import time
import subprocess

DEFAULT_WINDOW_MIN = int(os.getenv("POC_MONITOR_WINDOW_MIN", "15"))
DEFAULT_MIN_DISTANCE_BPS = float(os.getenv("POC_MONITOR_MIN_BPS", "12"))
DEFAULT_INTERVAL_SEC = int(os.getenv("POC_MONITOR_INTERVAL_SEC", "10"))


def get_db_url() -> str:
    url = os.getenv("BOT_TIMESCALE_URL")
    if url:
        return url
    host = os.getenv("BOT_DB_HOST", "localhost")
    port = os.getenv("BOT_DB_PORT", "5433")
    name = os.getenv("BOT_DB_NAME", "quantgambit_bot")
    user = os.getenv("BOT_DB_USER", "quantgambit")
    pw = os.getenv("BOT_DB_PASSWORD", "quantgambit_pw")
    return f"postgresql://{user}:{pw}@{host}:{port}/{name}"


SQL_COUNTS = """
WITH recent AS (
  SELECT timestamp, symbol, stage
  FROM recorded_decisions,
       jsonb_array_elements(stage_results) stage
  WHERE stage->>'stage' = 'signal_check'
    AND timestamp > now() - (%s || ' minutes')::interval
), calc AS (
  SELECT
    timestamp,
    symbol,
    round(((abs((stage->'rejection_detail'->'feature_snapshot'->>'distance_to_poc')::float)
          / nullif((stage->'rejection_detail'->'feature_snapshot'->>'price')::float, 0)
          * 10000))::numeric, 2) AS dist_bps
  FROM recent
)
SELECT
  count(*) AS total,
  count(*) FILTER (WHERE dist_bps >= %s) AS ge_min_bps
FROM calc;
"""

SQL_EV = """
WITH recent AS (
  SELECT timestamp, symbol, stage
  FROM recorded_decisions,
       jsonb_array_elements(stage_results) stage
  WHERE stage->>'stage' = 'signal_check'
    AND timestamp > now() - (%s || ' minutes')::interval
), calc AS (
  SELECT
    timestamp,
    symbol,
    round(((abs((stage->'rejection_detail'->'feature_snapshot'->>'distance_to_poc')::float)
          / nullif((stage->'rejection_detail'->'feature_snapshot'->>'price')::float, 0)
          * 10000))::numeric, 2) AS dist_bps
  FROM recent
), ev AS (
  SELECT
    r.timestamp,
    r.symbol,
    s->>'result' AS ev_result,
    s->'rejection_detail'->>'reject_code' AS ev_reject
  FROM recorded_decisions r,
       jsonb_array_elements(r.stage_results) s
  WHERE s->>'stage' = 'ev_gate'
    AND r.timestamp > now() - (%s || ' minutes')::interval
)
SELECT
  c.symbol,
  count(*) AS candidates,
  count(*) FILTER (WHERE e.ev_result = 'REJECT') AS ev_rejects,
  count(*) FILTER (WHERE e.ev_result = 'CONTINUE') AS ev_passes
FROM calc c
LEFT JOIN ev e
  ON c.symbol = e.symbol
 AND c.timestamp = e.timestamp
WHERE c.dist_bps >= %s
GROUP BY c.symbol
ORDER BY candidates DESC;
"""


def _psql_query(db_url: str, sql: str, params: list) -> str:
    escaped = sql
    for val in params:
        escaped = escaped.replace("%s", str(val), 1)
    cmd = ["psql", db_url, "-At", "-F", "|", "-c", escaped]
    return subprocess.check_output(cmd, text=True)


def run_once(db_url: str, window_min: int, min_bps: float) -> None:
    counts_raw = _psql_query(db_url, SQL_COUNTS, [window_min, min_bps]).strip()
    by_symbol_raw = _psql_query(db_url, SQL_EV, [window_min, window_min, min_bps]).strip()
    total = 0
    ge_min = 0
    if counts_raw:
        parts = counts_raw.split("|")
        total = int(parts[0] or 0)
        ge_min = int(parts[1] or 0)
    pct = (ge_min / total * 100.0) if total else 0.0
    print(
        f"Window={window_min}m | min_bps={min_bps:.2f} | total={total} | ge_min={ge_min} ({pct:.1f}%)"
    )
    if not by_symbol_raw:
        print("No EV-gate entries in window.")
        return
    print("By symbol (candidates >= min_bps):")
    for line in by_symbol_raw.splitlines():
        symbol, candidates, ev_rejects, ev_passes = line.split("|")
        print(
            f"  {symbol}: candidates={candidates} ev_pass={ev_passes} ev_reject={ev_rejects}"
        )


def main() -> None:
    window_min = int(os.getenv("POC_MONITOR_WINDOW_MIN", DEFAULT_WINDOW_MIN))
    min_bps = float(os.getenv("POC_MONITOR_MIN_BPS", DEFAULT_MIN_DISTANCE_BPS))
    interval = int(os.getenv("POC_MONITOR_INTERVAL_SEC", DEFAULT_INTERVAL_SEC))

    db_url = get_db_url()
    while True:
        run_once(db_url, window_min, min_bps)
        if interval <= 0:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
