# Cutover & Reconciliation Playbook

This document outlines procedures for deploying, migrating, and recovering
the quant-grade scalper system.

## Table of Contents

1. [Pre-Cutover Checklist](#pre-cutover-checklist)
2. [Deployment Procedure](#deployment-procedure)
3. [Rollback Procedure](#rollback-procedure)
4. [Reconciliation Operations](#reconciliation-operations)
5. [Emergency Procedures](#emergency-procedures)
6. [Dry-Run Script](#dry-run-script)

---

## Pre-Cutover Checklist

### 1. Environment Verification

```bash
# Verify all services are healthy
pm2 status

# Check Redis connectivity
redis-cli ping

# Check TimescaleDB connectivity
psql -h localhost -U quantgambit -d quantgambit -c "SELECT 1"

# Verify API credentials
python -m quantgambit.scripts.verify_credentials
```

### 2. Configuration Validation

```bash
# Validate config bundle
python -m quantgambit.scripts.validate_config --bundle-id production_v1

# Verify feature/model/calibrator artifacts
python -m quantgambit.scripts.verify_artifacts --manifest artifacts.json
```

### 3. Position & Order State

```bash
# Fetch current exchange state
python -m quantgambit.scripts.fetch_exchange_state --output pre_cutover_state.json

# Verify no stale positions in Redis
python -m quantgambit.scripts.check_stale_positions
```

### 4. Kill Switch Verification

```bash
# Verify kill switch is in expected state
python -m quantgambit.scripts.check_kill_switch

# Test kill switch triggering (paper mode)
python -m quantgambit.scripts.test_kill_switch --dry-run
```

---

## Deployment Procedure

### Phase 1: Preparation (T-10 minutes)

1. **Announce maintenance window**
   ```bash
   python -m quantgambit.scripts.send_alert --type maintenance --message "Deploying v2.0.0"
   ```

2. **Enable kill switch (no new entries)**
   ```bash
   python -m quantgambit.scripts.kill_switch --action enable --reason "Deployment"
   ```

3. **Wait for pending intents to clear**
   ```bash
   python -m quantgambit.scripts.wait_intents_clear --timeout 60
   ```

### Phase 2: Graceful Shutdown (T-5 minutes)

4. **Stop decision workers**
   ```bash
   pm2 stop quantgambit-decision-worker
   ```

5. **Wait for execution queue to drain**
   ```bash
   python -m quantgambit.scripts.wait_execution_drain --timeout 30
   ```

6. **Stop execution workers**
   ```bash
   pm2 stop quantgambit-execution-worker
   ```

7. **Capture final state snapshot**
   ```bash
   python -m quantgambit.scripts.snapshot_state --output pre_deploy_snapshot.json
   ```

### Phase 3: Deploy (T-0)

8. **Update codebase**
   ```bash
   git pull origin main
   pip install -r requirements.txt
   ```

9. **Run database migrations (if any)**
   ```bash
   python -m quantgambit.scripts.migrate
   ```

10. **Update config bundle**
    ```bash
    python -m quantgambit.scripts.apply_config --bundle-id production_v2
    ```

### Phase 4: Startup (T+5 minutes)

11. **Start market data service**
    ```bash
    pm2 start quantgambit-mds
    ```

12. **Wait for book coherence**
    ```bash
    python -m quantgambit.scripts.wait_book_coherent --symbols BTCUSDT,ETHUSDT --timeout 30
    ```

13. **Run full reconciliation**
    ```bash
    python -m quantgambit.scripts.reconcile --heal
    ```

14. **Start execution workers**
    ```bash
    pm2 start quantgambit-execution-worker
    ```

15. **Start decision workers**
    ```bash
    pm2 start quantgambit-decision-worker
    ```

### Phase 5: Verification (T+10 minutes)

16. **Verify decision flow**
    ```bash
    python -m quantgambit.scripts.verify_decision_flow --count 10
    ```

17. **Disable kill switch**
    ```bash
    python -m quantgambit.scripts.kill_switch --action disable
    ```

18. **Announce deployment complete**
    ```bash
    python -m quantgambit.scripts.send_alert --type info --message "Deployment complete"
    ```

---

## Rollback Procedure

### Immediate Rollback (within 5 minutes)

1. **Enable kill switch**
   ```bash
   python -m quantgambit.scripts.kill_switch --action enable --reason "Rollback"
   ```

2. **Stop all workers**
   ```bash
   pm2 stop all
   ```

3. **Restore previous code**
   ```bash
   git checkout HEAD~1
   pip install -r requirements.txt
   ```

4. **Restore previous config**
   ```bash
   python -m quantgambit.scripts.apply_config --bundle-id production_v1
   ```

5. **Run reconciliation**
   ```bash
   python -m quantgambit.scripts.reconcile --heal
   ```

6. **Restart services**
   ```bash
   pm2 start all
   ```

7. **Verify and disable kill switch**
   ```bash
   python -m quantgambit.scripts.verify_decision_flow --count 10
   python -m quantgambit.scripts.kill_switch --action disable
   ```

---

## Reconciliation Operations

### Scheduled Reconciliation

The reconciliation worker runs automatically every 30 seconds:

- Compares local position state with exchange
- Compares open orders with exchange
- Heals discrepancies automatically
- Emits events for all discrepancies

### Manual Reconciliation

```bash
# Run reconciliation with verbose output
python -m quantgambit.scripts.reconcile --verbose

# Reconcile specific symbol
python -m quantgambit.scripts.reconcile --symbol BTCUSDT

# Reconcile with healing disabled (report only)
python -m quantgambit.scripts.reconcile --no-heal

# Force full position sync from exchange
python -m quantgambit.scripts.reconcile --full-sync
```

### Discrepancy Types

| Type | Description | Auto-Heal Action |
|------|-------------|------------------|
| `position_missing_local` | Exchange has position, local doesn't | Add to local state |
| `position_missing_remote` | Local has position, exchange doesn't | Clear local state |
| `position_size_mismatch` | Sizes differ | Update local to match exchange |
| `order_missing_local` | Exchange has order, local doesn't | Cancel order (if config allows) |
| `order_missing_remote` | Local has order, exchange doesn't | Mark as canceled locally |

---

## Emergency Procedures

### Kill Switch Activation

```bash
# Immediate kill switch (blocks all trading)
python -m quantgambit.scripts.kill_switch --action enable --reason "Emergency"

# With position flatten
python -m quantgambit.scripts.kill_switch --action enable --flatten --reason "Emergency"
```

### Flatten All Positions

```bash
# Flatten all positions for all symbols
python -m quantgambit.scripts.flatten_all

# Flatten specific symbol
python -m quantgambit.scripts.flatten_all --symbol BTCUSDT
```

### Cancel All Orders

```bash
# Cancel all open orders
python -m quantgambit.scripts.cancel_all

# Cancel specific symbol
python -m quantgambit.scripts.cancel_all --symbol BTCUSDT
```

### State Reset

```bash
# Clear all local state and resync from exchange
python -m quantgambit.scripts.reset_state --confirm

# Clear specific symbol state
python -m quantgambit.scripts.reset_state --symbol BTCUSDT --confirm
```

---

## Dry-Run Script

Use the dry-run script to validate cutover procedures without executing them:

```bash
# Full dry-run of deployment
python -m quantgambit.scripts.dry_run_cutover --config deployment_config.yaml

# Dry-run with verbose output
python -m quantgambit.scripts.dry_run_cutover --config deployment_config.yaml --verbose

# Dry-run specific phase
python -m quantgambit.scripts.dry_run_cutover --config deployment_config.yaml --phase preparation
```

### Dry-Run Configuration

```yaml
# deployment_config.yaml
deployment:
  version: "2.0.0"
  config_bundle: "production_v2"
  
phases:
  preparation:
    timeout_s: 600
    steps:
      - verify_credentials
      - check_kill_switch
      - snapshot_state
      
  shutdown:
    timeout_s: 120
    steps:
      - stop_decision_workers
      - drain_execution_queue
      - stop_execution_workers
      
  deploy:
    timeout_s: 300
    steps:
      - update_code
      - run_migrations
      - apply_config
      
  startup:
    timeout_s: 300
    steps:
      - start_mds
      - wait_book_coherent
      - reconcile
      - start_workers
      
  verification:
    timeout_s: 120
    steps:
      - verify_decision_flow
      - disable_kill_switch

rollback:
  trigger_conditions:
    - decision_flow_failure
    - reconciliation_failure
    - latency_spike
```

---

## Monitoring During Cutover

### Key Metrics to Watch

| Metric | Alert Threshold | Action |
|--------|-----------------|--------|
| `decision_latency_p99_ms` | > 500 | Investigate or rollback |
| `book_staleness_count` | > 0 | Wait or rollback |
| `reconciliation_discrepancies` | > 10 | Investigate |
| `kill_switch_active` | unexpected | Investigate |
| `order_reject_rate` | > 10% | Investigate |

### Dashboard Queries

```sql
-- Recent decision latencies
SELECT
  date_trunc('minute', ts_wall) as minute,
  percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_total_ms) as p99
FROM decision_records
WHERE ts_wall > NOW() - INTERVAL '10 minutes'
GROUP BY 1
ORDER BY 1;

-- Reconciliation events
SELECT
  ts_wall,
  payload->>'discrepancy_type' as type,
  payload->>'details' as details,
  payload->>'healed' as healed
FROM events
WHERE type = 'ops.alert'
  AND payload->>'alert_type' = 'state_discrepancy'
  AND ts_wall > NOW() - INTERVAL '1 hour'
ORDER BY ts_wall DESC;
```

---

## Post-Cutover Validation

### 1. Verify Decision Flow

```bash
python -m quantgambit.scripts.verify_decision_flow --count 100 --timeout 60
```

### 2. Verify Execution Flow

```bash
python -m quantgambit.scripts.verify_execution_flow --place-test-order --paper
```

### 3. Verify Reconciliation

```bash
python -m quantgambit.scripts.reconcile --report-only
```

### 4. Verify Latencies

```bash
python -m quantgambit.scripts.check_latencies --threshold-p99-ms 100
```

### 5. Sign-Off Checklist

- [ ] All services running (pm2 status)
- [ ] Decision flow verified
- [ ] Execution flow verified
- [ ] No reconciliation discrepancies
- [ ] Latencies within SLO
- [ ] Kill switch disabled
- [ ] Alerts configured
- [ ] Rollback plan documented
