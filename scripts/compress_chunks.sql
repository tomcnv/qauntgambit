-- Compress decision_events chunk
SELECT compress_chunk('_timescaledb_internal._hyper_1_60_chunk');

-- Compress prediction_events chunk  
SELECT compress_chunk('_timescaledb_internal._hyper_3_57_chunk');

-- Compress latency_events chunk
SELECT compress_chunk('_timescaledb_internal._hyper_4_61_chunk');

-- Compress trade_records chunk
SELECT compress_chunk('_timescaledb_internal._hyper_15_68_chunk');

-- Show final sizes
SELECT hypertable_name, 
       pg_size_pretty(hypertable_size(format('%I.%I', hypertable_schema, hypertable_name)::regclass)) as total_size
FROM timescaledb_information.hypertables
ORDER BY hypertable_size(format('%I.%I', hypertable_schema, hypertable_name)::regclass) DESC;
