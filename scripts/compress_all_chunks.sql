-- Enable compression on tables that don't have it yet
ALTER TABLE guardrail_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');
ALTER TABLE orderbook_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');
ALTER TABLE position_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');

-- Compress all uncompressed chunks
SELECT compress_chunk('_timescaledb_internal._hyper_10_59_chunk');
SELECT compress_chunk('_timescaledb_internal._hyper_9_62_chunk');
SELECT compress_chunk('_timescaledb_internal._hyper_13_67_chunk');
SELECT compress_chunk('_timescaledb_internal._hyper_7_63_chunk');
SELECT compress_chunk('_timescaledb_internal._hyper_26_615_chunk');
SELECT compress_chunk('_timescaledb_internal._hyper_26_616_chunk');
SELECT compress_chunk('_timescaledb_internal._hyper_28_625_chunk');
SELECT compress_chunk('_timescaledb_internal._hyper_28_626_chunk');

-- Show final sizes
SELECT hypertable_name, 
       pg_size_pretty(hypertable_size(format('%I.%I', hypertable_schema, hypertable_name)::regclass)) as total_size
FROM timescaledb_information.hypertables
ORDER BY hypertable_size(format('%I.%I', hypertable_schema, hypertable_name)::regclass) DESC;
