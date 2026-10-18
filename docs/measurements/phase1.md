# Phase 1 measurements

Every number below is followed by the exact command and its raw output. Laptop: Windows 11, 20 logical CPUs, 15.6 GB RAM; Docker Desktop 4.92.0 (Engine 29.8.0), WSL2 VM with 8.1 GB.

## M1. Trace propagation and dependency edges (2026-10-18T18:12:14Z)

```
$ bash tools/check_propagation.sh
# traces in the last 5 min by number of distinct services
1	13
2	75
3	2
4	298
# checkout traces (gateway POST /checkout) that reach all four services
298	310
# service_edges (parent -> child, calls)
gateway	orders	376
orders	inventory	302
orders	payments	299
payments	inventory	297
payments	provider	297
# logs carrying trace context
308	308
```

Checkouts that do not reach four services are the traffic generator's deliberately invalid requests (422 at orders) and requests made while services were starting.

## M2. Demo Postgres commit stalls, before/after synchronous_commit=off (2026-10-18)

Spontaneous gateway incidents opened with no fault injected (18:27:28, 18:34:33). Drill-down: inventory/orders commit statements stalled 0.5-1.4 s while every container's CPU was idle -> WAL fsync on the shared Docker Desktop disk. Fix at 18:36:19: `ALTER SYSTEM SET synchronous_commit = off` on the demo database only (persisted as a compose command). Commit statements = CLIENT spans named WITH/UPDATE/INSERT; the injected pool_exhaustion window is excluded.

```
$ curl ... --data-binary "SELECT start_ts >= '2026-10-18 18:36:19' AS after_change, count() n, countIf(duration_ms > 300) over_300ms, round(quantile(0.99)(duration_ms),1) p99, round(max(duration_ms)) mx FROM spans WHERE attrs['span.kind']='CLIENT' AND service IN ('inventory','orders') AND name IN ('WITH','UPDATE','INSERT') AND start_ts BETWEEN '2026-10-18 18:12:00' AND '2026-10-18 18:56:00' AND NOT (start_ts BETWEEN '2026-10-18 18:21:35' AND '2026-10-18 18:23:10') GROUP BY after_change ORDER BY after_change FORMAT TSVWithNames"
after_change	n	over_300ms	p99	mx
0	11946	69	34.2	1370
1	10151	0	1.9	23
```

## M3. Memory at idle and with normal demo traffic (2026-10-18)

Counts only this stack's containers (`sentry-rca-*`). Another unrelated compose stack (`deploy-*`, ~1.7 GB) was running on the same Docker VM and is excluded from the totals but included in the VM and host free figures.

```
$ docker compose -f deploy/compose.yaml stop traffic; sleep 90; bash tools/memory.sh "idle: ..."
## memory: idle: full stack, traffic generator stopped @ 2026-10-18T19:53:01Z
$ docker stats --no-stream (sentry-rca-*)
sentry-rca-alerting-1	31.22MiB / 160MiB	0.01%
sentry-rca-archiver-1	39.96MiB / 160MiB	0.00%
sentry-rca-batchjob-1	43.96MiB / 128MiB	0.25%
sentry-rca-clickhouse-1	719.1MiB / 1.5GiB	9.13%
sentry-rca-demo-postgres-1	34.75MiB / 256MiB	5.82%
sentry-rca-gateway-1	52.87MiB / 256MiB	0.26%
sentry-rca-inventory-1	56.37MiB / 768MiB	0.24%
sentry-rca-orders-1	54.33MiB / 768MiB	0.25%
sentry-rca-otel-collector-1	194.1MiB / 320MiB	0.52%
sentry-rca-payments-1	144.7MiB / 768MiB	0.30%
sentry-rca-postgres-1	31.01MiB / 256MiB	8.90%
sentry-rca-processor-logs-1	34.46MiB / 192MiB	0.10%
sentry-rca-processor-metrics-1	36.17MiB / 192MiB	0.22%
sentry-rca-processor-traces-1	38.64MiB / 192MiB	0.21%
sentry-rca-redpanda-1	234MiB / 768MiB	1.11%
TOTAL	1732.2 MiB (15 containers)
$ docker run --rm alpine:3.20 free -m   (the Docker Desktop WSL2 VM)
              total        used        free      shared  buff/cache   available
Mem:           7751        4434         221         151        3096        2974
Swap:          2048         316        1732
$ powershell (Get-CimInstance Win32_OperatingSystem) free/total physical memory (host)
host free 1,118 MiB of 16,004 MiB

$ docker compose -f deploy/compose.yaml start traffic; sleep 120; bash tools/memory.sh "normal: ..."
## memory: normal: demo traffic (BASE_RPS=4) @ 2026-10-18T19:55:14Z
$ docker stats --no-stream (sentry-rca-*)
sentry-rca-alerting-1	31.22MiB / 160MiB	0.02%
sentry-rca-archiver-1	39.96MiB / 160MiB	0.00%
sentry-rca-batchjob-1	43.96MiB / 128MiB	0.45%
sentry-rca-clickhouse-1	763.7MiB / 1.5GiB	20.42%
sentry-rca-demo-postgres-1	34.84MiB / 256MiB	0.52%
sentry-rca-gateway-1	53.12MiB / 256MiB	2.85%
sentry-rca-inventory-1	56.38MiB / 768MiB	3.30%
sentry-rca-orders-1	54.32MiB / 768MiB	4.43%
sentry-rca-otel-collector-1	206.9MiB / 320MiB	2.21%
sentry-rca-payments-1	125.9MiB / 768MiB	3.37%
sentry-rca-postgres-1	31.02MiB / 256MiB	0.01%
sentry-rca-processor-logs-1	33.1MiB / 192MiB	0.67%
sentry-rca-processor-metrics-1	36.17MiB / 192MiB	0.66%
sentry-rca-processor-traces-1	38.52MiB / 192MiB	0.93%
sentry-rca-redpanda-1	235.3MiB / 768MiB	1.75%
sentry-rca-traffic-1	22.06MiB / 96MiB	0.83%
TOTAL	1799.4 MiB (16 containers)
$ docker run --rm alpine:3.20 free -m   (the Docker Desktop WSL2 VM)
              total        used        free      shared  buff/cache   available
Mem:           7751        4477         157         151        3117        2931
Swap:          2048         316        1732
$ powershell (Get-CimInstance Win32_OperatingSystem) free/total physical memory (host)
host free 1,332 MiB of 16,004 MiB
```

## M4. Redpanda down for 60 s (SPEC §15 row 17)

Command: `docker compose stop redpanda` at 19:55:45, `start` at 19:56:46; Collector queue sampled from its Prometheus endpoint (localhost:8888) every 20 s / 15 s.

```
before:            queue_size logs 0, metrics 0, traces 0
down +20 s:        queue_size logs 22, metrics 22, traces 83
down +40 s:        queue_size logs 39, metrics 42, traces 160
down +60 s:        queue_size logs 60, metrics 62, traces 240      (bound: 2000 batches per signal)
after restart +15: queue_size logs 0, metrics 0, traces 0
otelcol_exporter_enqueue_failed_* / send_failed_*: never emitted (never incremented)
processors and alerting: "Up 47 minutes" after the outage (no crash, no restart)

$ curl ... --data-binary "SELECT toStartOfInterval(start_ts, INTERVAL 20 SECOND) t, count() spans, uniqExact(trace_id) traces FROM spans FINAL WHERE start_ts BETWEEN '2026-10-18 19:55:00' AND '2026-10-18 19:57:40' GROUP BY t ORDER BY t FORMAT TSVWithNames"
t	spans	traces
2026-10-18 19:55:00	1852	57
2026-10-18 19:55:20	2184	69
2026-10-18 19:55:40	1946	63
2026-10-18 19:56:00	1921	60
2026-10-18 19:56:20	2221	74
2026-10-18 19:56:40	1988	71
2026-10-18 19:57:00	2339	74
2026-10-18 19:57:20	1602	57
```

No gap across the outage: the queue held ~60 s of telemetry in 12 % of its bound and drained within 15 s. Overflow (a longer outage) was not exercised; at the observed fill rate (240 trace batches/min) the 2,000-batch queue lasts ~8 min.
