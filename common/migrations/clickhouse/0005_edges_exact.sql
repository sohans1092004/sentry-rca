-- Amendment A33: service_edges counts calls exactly. uniq() is approximate (hash-sampled); the eval's
-- backend agreement check (A26) found a 5,717-call edge counted 5,718 by an exact count. Rebuilt with
-- uniqExact, then refilled from the spans of the last day (older edges are not needed for a scope).
DROP VIEW IF EXISTS service_edges_mv;
DROP TABLE IF EXISTS service_edges;
CREATE TABLE service_edges (
  tenant_id LowCardinality(String), bucket DateTime,
  parent_service LowCardinality(String), child_service LowCardinality(String),
  calls AggregateFunction(uniqExact, String)
) ENGINE = AggregatingMergeTree
  ORDER BY (tenant_id, bucket, parent_service, child_service)
  TTL bucket + INTERVAL 7 DAY;
CREATE MATERIALIZED VIEW service_edges_mv TO service_edges AS
SELECT tenant_id, toStartOfFiveMinutes(start_ts) AS bucket, service AS parent_service,
       if(attrs['peer.service'] != '', attrs['peer.service'], attrs['server.address']) AS child_service,
       uniqExactState(span_id) AS calls
FROM spans
WHERE attrs['span.kind'] = 'CLIENT' AND child_service != '' AND child_service != service
GROUP BY tenant_id, bucket, parent_service, child_service;
INSERT INTO service_edges
SELECT tenant_id, toStartOfFiveMinutes(start_ts) AS bucket, service AS parent_service,
       if(attrs['peer.service'] != '', attrs['peer.service'], attrs['server.address']) AS child_service,
       uniqExactState(span_id) AS calls
FROM spans
WHERE attrs['span.kind'] = 'CLIENT' AND child_service != '' AND child_service != service
  AND start_ts >= now() - INTERVAL 1 DAY
GROUP BY tenant_id, bucket, parent_service, child_service;
