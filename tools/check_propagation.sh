#!/usr/bin/env bash
# Trace propagation and dependency edges, from live ClickHouse data.
# Traces younger than 60 s are excluded: each service exports spans on its own 1 s batch schedule, so
# the newest traces are briefly incomplete in ClickHouse (seen as "201 checkouts with 2 services").
q(){ curl -s "http://localhost:8123/?user=sentry&password=sentry&database=sentry" --data-binary "$1"; }
W="start_ts BETWEEN now() - INTERVAL 6 MINUTE AND now() - INTERVAL 1 MINUTE"
echo "# checkout traces by gateway response status and number of services (5 min, older than 60 s)"
q "SELECT status, n_services, count() FROM (SELECT trace_id, uniqExact(service) n_services, anyIf(attrs['http.response.status_code'], service = 'gateway' AND name = 'POST /checkout') status FROM spans WHERE $W GROUP BY trace_id HAVING has(groupArray(name), 'POST /checkout') AND min(start_ts) >= now() - INTERVAL 6 MINUTE) GROUP BY status, n_services ORDER BY status, n_services FORMAT TSVWithNames"
echo "# service_edges (parent -> child, calls)"
q "SELECT parent_service, child_service, uniqMerge(calls) FROM service_edges GROUP BY 1,2 ORDER BY 1,2"
echo "# logs carrying trace context"
q "SELECT countIf(trace_id != ''), count() FROM logs WHERE ts > now() - INTERVAL 6 MINUTE"
