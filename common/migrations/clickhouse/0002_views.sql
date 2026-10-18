-- service_edges (SPEC §4.1): parent -> child service calls per 5-minute bucket.
-- A materialised view only sees the inserted block, so it cannot join a child span to a parent
-- span that arrived in another batch. Each CLIENT span already names its callee
-- (peer.service, else server.address), so the edge is derived from that one span.
-- uniq(span_id) keeps redelivered spans from double-counting calls.
CREATE TABLE IF NOT EXISTS service_edges (
  tenant_id LowCardinality(String), bucket DateTime,
  parent_service LowCardinality(String), child_service LowCardinality(String),
  calls AggregateFunction(uniq, String)
) ENGINE = AggregatingMergeTree
  ORDER BY (tenant_id, bucket, parent_service, child_service)
  TTL bucket + INTERVAL 7 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS service_edges_mv TO service_edges AS
SELECT tenant_id, toStartOfFiveMinutes(start_ts) AS bucket, service AS parent_service,
       if(attrs['peer.service'] != '', attrs['peer.service'], attrs['server.address']) AS child_service,
       uniqState(span_id) AS calls
FROM spans
WHERE attrs['span.kind'] = 'CLIENT' AND child_service != '' AND child_service != service
GROUP BY tenant_id, bucket, parent_service, child_service;

-- metrics_1h (SPEC §4.1, §4.4): 1-hour downsample kept 90 days.
-- ponytail: the MV fires on insert, before ReplacingMergeTree dedup, so a redelivered batch
-- inflates sum_value/points for its hour (avg/min/max are unaffected by exact duplicates).
-- Upgrade path: a refreshable MV over FINAL if downsampled counts ever need to be exact.
CREATE TABLE IF NOT EXISTS metrics_1h (
  tenant_id LowCardinality(String), service LowCardinality(String),
  metric LowCardinality(String), labels_hash UInt64,
  labels SimpleAggregateFunction(any, Map(String, String)), hour DateTime,
  avg_value AggregateFunction(avg, Float64),
  min_value SimpleAggregateFunction(min, Float64),
  max_value SimpleAggregateFunction(max, Float64),
  sum_value SimpleAggregateFunction(sum, Float64),
  points SimpleAggregateFunction(sum, UInt64)
) ENGINE = AggregatingMergeTree
  ORDER BY (tenant_id, service, metric, labels_hash, hour)
  TTL hour + INTERVAL 90 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_1h_mv TO metrics_1h AS
SELECT tenant_id, service, metric, cityHash64(mapKeys(labels), mapValues(labels)) AS labels_hash,
       labels, toStartOfHour(ts) AS hour,
       avgState(value) AS avg_value, min(value) AS min_value, max(value) AS max_value,
       sum(value) AS sum_value, toUInt64(count()) AS points
FROM metrics
GROUP BY tenant_id, service, metric, labels_hash, labels, hour;
