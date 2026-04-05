# Schema Versioning & Data Retention

This document defines the schema versioning strategy for EventEnvelope and
DecisionRecord, along with rotation and retention policies.

## Schema Versioning

### Version Format

All schemas use semantic versioning embedded in the `v` field:

```json
{
  "v": 1,
  "type": "decision",
  ...
}
```

### Breaking vs Non-Breaking Changes

**Non-breaking (minor version bump):**
- Adding optional fields
- Adding new event types
- Relaxing validation rules

**Breaking (major version bump):**
- Removing fields
- Changing field types
- Changing field semantics
- Renaming fields

### EventEnvelope Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "EventEnvelope",
  "description": "Canonical event wrapper for all system events",
  "type": "object",
  "required": ["v", "type", "source", "ts_wall", "ts_mono", "trace_id", "payload"],
  "properties": {
    "v": {
      "type": "integer",
      "description": "Schema version",
      "minimum": 1
    },
    "type": {
      "type": "string",
      "description": "Event type (e.g., 'decision', 'exec.intent')"
    },
    "source": {
      "type": "string",
      "description": "Event source identifier"
    },
    "symbol": {
      "type": ["string", "null"],
      "description": "Trading symbol (optional)"
    },
    "ts_wall": {
      "type": "number",
      "description": "Wall clock timestamp (epoch seconds)"
    },
    "ts_mono": {
      "type": "number",
      "description": "Monotonic timestamp (seconds)"
    },
    "trace_id": {
      "type": "string",
      "description": "Correlation trace ID"
    },
    "seq": {
      "type": ["integer", "null"],
      "description": "Sequence number (optional)"
    },
    "payload": {
      "type": "object",
      "description": "Event-specific payload"
    }
  }
}
```

### DecisionRecord Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "DecisionRecord",
  "description": "Complete audit record of a trading decision",
  "type": "object",
  "required": ["schema_version", "record_id", "trace_id", "symbol", "outcome"],
  "properties": {
    "schema_version": { "type": "integer", "minimum": 1 },
    "record_id": { "type": "string" },
    "trace_id": { "type": "string" },
    "symbol": { "type": "string" },
    "ts_wall": { "type": "number" },
    "ts_mono": { "type": "number" },
    "ts_book": { "type": "number" },
    
    "bundle_id": { "type": "string" },
    "feature_set_version_id": { "type": "string" },
    "model_version_id": { "type": "string" },
    "calibrator_version_id": { "type": "string" },
    "risk_profile_version_id": { "type": "string" },
    "execution_policy_version_id": { "type": "string" },
    
    "book": {
      "type": "object",
      "properties": {
        "bid": { "type": ["number", "null"] },
        "ask": { "type": ["number", "null"] },
        "mid": { "type": ["number", "null"] },
        "spread_bps": { "type": ["number", "null"] },
        "seq": { "type": ["integer", "null"] },
        "is_quoteable": { "type": "boolean" }
      }
    },
    
    "signal_s": { "type": "number" },
    "vol_hat": { "type": "number" },
    "w_current": { "type": "number" },
    "w_target": { "type": "number" },
    "delta_w": { "type": "number" },
    
    "outcome": {
      "type": "string",
      "enum": [
        "no_action",
        "intent_emitted",
        "blocked_kill_switch",
        "blocked_book_unsafe",
        "blocked_deadband",
        "blocked_churn_guard",
        "error_feature_build",
        "error_model_infer"
      ]
    },
    
    "intent_ids": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

---

## Data Rotation

### Event Files

Events are recorded to JSONL files with rotation:

```
events/
  ├── 2024/
  │   ├── 01/
  │   │   ├── 01/
  │   │   │   ├── events_00.jsonl.gz
  │   │   │   ├── events_01.jsonl.gz
  │   │   │   └── ...
```

**Rotation Policy:**
- New file every hour
- Compress after rotation (gzip)
- File naming: `events_{HH}.jsonl`

### Configuration

```yaml
event_recording:
  enabled: true
  base_path: /data/events
  rotation_interval_h: 1
  compression: gzip
  max_file_size_mb: 100
```

---

## Data Retention

### Retention Tiers

| Data Type | Hot (SSD) | Warm (HDD) | Archive (S3) | Delete |
|-----------|-----------|------------|--------------|--------|
| Raw events | 7 days | 30 days | 1 year | After 1 year |
| Decision records | 30 days | 90 days | 2 years | After 2 years |
| Order events | 30 days | 1 year | 5 years | After 5 years |
| Position snapshots | 7 days | 30 days | 1 year | After 1 year |

### TimescaleDB Compression

```sql
-- Enable compression on decision_records hypertable
SELECT add_compression_policy('decision_records', INTERVAL '7 days');

-- Configure compression
ALTER TABLE decision_records SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'symbol',
  timescaledb.compress_orderby = 'ts_wall DESC'
);
```

### Retention Jobs

```sql
-- Add retention policy (90 day hot retention)
SELECT add_retention_policy('decision_records', INTERVAL '90 days');

-- Archive to S3 before deletion
CREATE OR REPLACE FUNCTION archive_before_delete()
RETURNS TRIGGER AS $$
BEGIN
  -- Copy to S3 via pg_cron job
  PERFORM archive_chunk_to_s3(OLD.chunk_name);
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;
```

---

## Backward Compatibility

### Reading Old Schemas

```python
def read_event(data: dict) -> EventEnvelope:
    """Read event with schema migration."""
    version = data.get("v", 1)
    
    if version == 1:
        return EventEnvelope(**data)
    elif version == 2:
        # Migration from v1 to v2
        migrated = migrate_v1_to_v2(data)
        return EventEnvelope(**migrated)
    else:
        raise ValueError(f"Unknown schema version: {version}")

def migrate_v1_to_v2(data: dict) -> dict:
    """Migrate v1 event to v2."""
    # Example: rename field
    if "old_field" in data:
        data["new_field"] = data.pop("old_field")
    return data
```

### Compatibility Tests

```python
def test_read_v1_events():
    """Verify old events can still be read."""
    v1_events = load_test_events("testdata/v1_events.jsonl")
    
    for event in v1_events:
        # Should not raise
        parsed = read_event(event)
        assert parsed is not None

def test_schema_evolution():
    """Verify schema changes are backward compatible."""
    # Old producer, new consumer
    v1_event = produce_v1_event()
    parsed = read_event(v1_event)
    assert parsed.type is not None
    
    # New producer, old consumer
    v2_event = produce_v2_event()
    # Should work if only additive changes
    v1_parsed = read_v1_event(v2_event)
    assert v1_parsed is not None
```

---

## Storage Estimates

### Per-Decision Storage

| Component | Size |
|-----------|------|
| DecisionRecord (JSON) | ~2 KB |
| With full pipeline outputs | ~5 KB |
| Compressed (gzip) | ~0.5-1 KB |

### Daily Volume (100k decisions/day)

| Storage | Size |
|---------|------|
| Raw events | ~500 MB/day |
| Compressed | ~100 MB/day |
| Monthly (compressed) | ~3 GB |
| Yearly (compressed) | ~36 GB |

### TimescaleDB

```sql
-- Check hypertable size
SELECT hypertable_size('decision_records');

-- Check chunk sizes
SELECT chunk_name, 
       pg_size_pretty(total_bytes) as size
FROM timescaledb_information.chunks
WHERE hypertable_name = 'decision_records'
ORDER BY total_bytes DESC
LIMIT 10;
```
