# DBA Runbook – Position Governance

## Purpose

Operational checklist for keeping the *one position per symbol* guarantee healthy after deployments or incidents.

---

## 1. Monitor the Unique Index

The constraint is enforced by the partial index `idx_fast_scalper_positions_unique_open`.

### Check for duplicates
```sql
SELECT user_id, symbol, COUNT(*) AS position_count
FROM fast_scalper_positions
WHERE status = 'open'
GROUP BY user_id, symbol
HAVING COUNT(*) > 1;
```
✅ Expected: **0 rows**

### Monitor index size
```sql
SELECT pg_size_pretty(pg_relation_size('idx_fast_scalper_positions_unique_open'));
```
If the index size grows unexpectedly, run `VACUUM (VERBOSE, ANALYZE) fast_scalper_positions;`.

---

## 2. Clean Up Duplicates (if any)

Use the scripted cleanup tool (safe for repeated use):
```bash
cd deeptrader-python
python scripts/cleanup_duplicate_positions.py --dsn postgresql://user:pass@host:5432/deeptrader
```
- `--dry-run` to inspect without modifying data.
- Logs detail how many duplicates were closed.

After cleanup, re-run the migration if necessary:
```bash
psql -d deeptrader -f fast_scalper/migrations/001_add_position_unique_constraint.sql
```

---

## 3. Observe Runtime Metrics

The monitoring API now publishes guard counters:
```bash
curl http://localhost:3001/api/dashboard | jq '.position_governance'
```
Metrics include:
- `order_execution_stage_duplicate_block`
- `order_executor_duplicate_block`
- `state_manager_overwrite_warning`

Set alerts if any counter increases rapidly—this indicates race conditions that need investigation.

---

## 4. Logging Checklist

- All defensive blocks log via `fast_scalper.logger`.
- Search for `duplicate position` or `Position overwrite detected` in `fast_scalper.log`.
- If logs appear often, gather context (`symbol/profile/reason`) and alert the engineering team.

---

## 5. Deployment Verification

After migrations / major releases:
1. Run governance tests: `venv/bin/pytest tests/test_position_governance.py`
2. Hit the monitoring endpoint to ensure counters exist.
3. Verify the unique index still exists: `\d fast_scalper_positions`

---

## 6. Emergency Playbook

| Scenario | Action |
|----------|--------|
| Migration fails because of duplicates | Run cleanup script, rerun migration |
| Index missing (dropped accidentally) | Rerun migration SQL, recheck constraint |
| Counters exploding | Pause trading, inspect logs, file incident |
| Manual database edits required | Always close duplicates by setting `status='closed'`, **never delete rows** |

---

## 7. Contacts / Ownership

- **Primary**: Python trading team
- **Secondary**: Platform/DBA on-call
- **Escalation**: #trading-ops Slack channel with context and metrics output

---

Stay disciplined: single net position per symbol is a **hard requirement**. This runbook keeps it that way.





