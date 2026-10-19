-- metrics_1h is computed by a job from deduplicated raw rows, not by a materialised view
-- (Amendment A10): the view fired on insert, before ReplacingMergeTree dedup, so a redelivered
-- batch was counted twice. Re-running the job for an hour replaces that hour (newest computed_at).
DROP VIEW IF EXISTS metrics_1h_mv;
DROP TABLE IF EXISTS metrics_1h;
CREATE TABLE IF NOT EXISTS metrics_1h (
  tenant_id LowCardinality(String), service LowCardinality(String),
  metric LowCardinality(String), labels_hash UInt64, labels Map(String, String), hour DateTime,
  avg_value Float64, min_value Float64, max_value Float64, sum_value Float64, points UInt64,
  computed_at DateTime64(3)
) ENGINE = ReplacingMergeTree(computed_at)
  ORDER BY (tenant_id, service, metric, labels_hash, hour)
  TTL hour + INTERVAL 90 DAY;
