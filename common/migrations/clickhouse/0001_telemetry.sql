-- SPEC §4.1. Dedup is by the full sorting key, which ends in the stable ID.
CREATE TABLE IF NOT EXISTS metrics (
  tenant_id LowCardinality(String), service LowCardinality(String),
  metric LowCardinality(String), labels Map(String, String),
  ts DateTime64(3), value Float64, point_id UUID
) ENGINE = ReplacingMergeTree
  ORDER BY (tenant_id, service, metric, ts, point_id)
  TTL toDateTime(ts) + INTERVAL 7 DAY;

CREATE TABLE IF NOT EXISTS logs (
  tenant_id LowCardinality(String), service LowCardinality(String),
  ts DateTime64(3), severity LowCardinality(String), body String,
  trace_id String, span_id String, attrs Map(String, String), log_id UUID
) ENGINE = ReplacingMergeTree
  ORDER BY (tenant_id, service, ts, log_id)
  TTL toDateTime(ts) + INTERVAL 7 DAY;

CREATE TABLE IF NOT EXISTS spans (
  tenant_id LowCardinality(String), trace_id String, span_id String,
  parent_span_id String, service LowCardinality(String), name String,
  start_ts DateTime64(3), duration_ms Float64, status LowCardinality(String),
  attrs Map(String, String)
) ENGINE = ReplacingMergeTree
  ORDER BY (tenant_id, trace_id, span_id)
  TTL toDateTime(start_ts) + INTERVAL 7 DAY;
