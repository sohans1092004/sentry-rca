#!/usr/bin/env bash
# Trace propagation and dependency edges, from live ClickHouse data.
q(){ curl -s "http://localhost:8123/?user=sentry&password=sentry&database=sentry" --data-binary "$1"; }
echo "# traces in the last 5 min by number of distinct services"
q "SELECT n, count() FROM (SELECT trace_id, uniqExact(service) n FROM spans WHERE start_ts > now() - INTERVAL 5 MINUTE GROUP BY trace_id) GROUP BY n ORDER BY n"
echo "# checkout traces (gateway POST /checkout) that reach all four services"
q "SELECT countIf(n = 4), count() FROM (SELECT trace_id, uniqExact(service) n FROM spans WHERE start_ts > now() - INTERVAL 5 MINUTE GROUP BY trace_id HAVING has(groupArray(name), 'POST /checkout') AND has(groupArray(service), 'gateway'))"
echo "# service_edges (parent -> child, calls)"
q "SELECT parent_service, child_service, uniqMerge(calls) FROM service_edges GROUP BY 1,2 ORDER BY 1,2"
echo "# logs carrying trace context"
q "SELECT countIf(trace_id != ''), count() FROM logs"
