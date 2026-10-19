-- Deploys live in ClickHouse next to the telemetry, live and in every eval database, so one query
-- serves both (Amendment A9). A deploy row is written once with both timestamps, never updated.
CREATE TABLE IF NOT EXISTS deploys (
  id String, tenant_id LowCardinality(String), service LowCardinality(String), version String,
  started_at DateTime64(3), finished_at DateTime64(3)
) ENGINE = ReplacingMergeTree
  ORDER BY (tenant_id, service, finished_at, id);
