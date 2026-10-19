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

## M5. Ingestion ceiling (SPEC §17, §1.2)

Events = metric points + log records + spans, one third each, from `tools/ceiling.py` (8-16 Python sender processes on the Windows host). Lag = uncommitted messages in each processor's consumer group, summed over partitions. Each run's raw JSON (incl. full `docker stats` per step) is in `runs/ceiling*.json` (local).

### Run A: through the Collector, 100 events/request (`uv run python tools/ceiling.py --start 1000 --step-s 60 --max 40000`)

```
target_eps  sent_eps  refused_eps  lag_mid(msgs)  lag_end(msgs)  growing
1000 986 n/a 3 13 False
2000 1974 n/a 31 2 False
3000 2960 n/a 17 9 False
4000 3947 n/a 10 19 False
5000 4937 n/a 17 11 False
6000 5907 n/a 18 29 False
8000 7898 n/a 25 15 False
10000 9883 n/a 0 25 False
12500 12335 n/a 9 7 False
15000 14055 n/a 18 38 False
20000 15589 n/a 8 14 False
25000 16936 n/a 30 29 False
30000 16708 n/a 8 17 False
40000 16936 n/a 29 29 False
```
Accepted throughput plateaus at ~16.9k events/s while lag stays bounded: the limit was the generator's per-request cost (one blocking POST at a time, through Docker Desktop's port proxy), not the pipeline. This run sampled `docker stats` after each step ended (a tool bug, since fixed), so it has no CPU attribution.

### Run B: through the Collector, 500 events/request (`uv run python tools/ceiling.py --start 15000 --step-s 60 --procs 16 --batch 500`)

```
target_eps  sent_eps  refused_eps  lag_mid(msgs)  lag_end(msgs)  growing
15000 14720 0 29 41 False
20000 19631 0 44 30 False
25000 24578 0 55 52 False
30000 27435 2023 31 37 False
40000 33904 5331 57 33 False
50000 43453 5532 65 51 False
60000 48855 9906 55 25 False
80000 64756 13195 126 24 False
-- target 60000, docker stats mid-step:
sentry-rca-processor-logs-1	23.74%	75.22MiB / 192MiB
sentry-rca-processor-metrics-1	29.99%	74.65MiB / 192MiB
sentry-rca-processor-traces-1	21.84%	81.28MiB / 192MiB
sentry-rca-otel-collector-1	22.96%	240.2MiB / 320MiB
sentry-rca-clickhouse-1	18.87%	737.5MiB / 1.5GiB
sentry-rca-redpanda-1	13.65%	335.5MiB / 768MiB
-- target 80000, docker stats mid-step:
sentry-rca-processor-logs-1	59.35%	111.7MiB / 192MiB
sentry-rca-processor-metrics-1	79.14%	102.7MiB / 192MiB
sentry-rca-processor-traces-1	42.93%	104.3MiB / 192MiB
sentry-rca-otel-collector-1	33.32%	207.9MiB / 320MiB
sentry-rca-clickhouse-1	37.56%	760.9MiB / 1.5GiB
sentry-rca-redpanda-1	10.57%	335.8MiB / 768MiB
```
Lag never grows without bound through the Collector: above ~25k events/s offered, the Collector's `memory_limiter` (limit 200 MiB in a 320 MiB container) refuses requests (`otelcol_receiver_refused_*`), back-pressure that real SDKs retry. Highest accepted: 64,756 events/s at 80k offered (13,195/s refused).

### Run C: direct into Redpanda, before the batch fix (`... --direct --start 20000 --procs 12 --batch 500`, stopped at 125k)

```
target_eps  sent_eps  refused_eps  lag_mid(msgs)  lag_end(msgs)  growing
20000 19662 0 43 5 False
25000 24592 0 54 20 False
30000 29426 0 30 41 False
40000 39128 0 81 54 False
50000 48871 0 92 88 False
60000 58791 0 120 107 False
80000 78540 0 358 348 False
100000 97733 0 875 2592 False
125000 121455 0 7052 11597 False
150000 145303 0 19152 27714 False

$ docker events --since 15m --filter event=oom --filter event=die
sentry-rca-processor-metrics-1 oom; die exit=137
sentry-rca-processor-logs-1 oom; die exit=137   (restarts=2)
```
Bug: batches were bounded by message count (500); with 500-event messages that is ~250k rows of Python objects, over the 192 MiB limit. A restarted processor faced the same backlog and was killed again. Fix: batches bounded by payload bytes (`processors/runner.py` `take_batch`, 1 MiB). The fixed processors then drained the ~47.5k-message backlog this run left behind with 0 restarts.

### Run D: direct into Redpanda, fixed processors (`uv run python tools/ceiling.py --direct --start 40000 --step-s 60 --procs 12 --batch 500`)

```
target_eps  sent_eps  refused_eps  lag_mid(msgs)  lag_end(msgs)  growing
40000 39374 0 2126 57 False
50000 49203 0 112 124 True
60000 59011 0 99 76 False
80000 78181 0 146 101 False
100000 98204 0 159 177 False
125000 121689 0 469 650 True
150000 146677 0 2446 4029 True
-- target 100000, docker stats mid-step:
sentry-rca-processor-traces-1	54.49%	67.08MiB / 192MiB
sentry-rca-processor-metrics-1	67.32%	81.28MiB / 192MiB
sentry-rca-processor-logs-1	78.62%	65.08MiB / 192MiB
sentry-rca-otel-collector-1	2.73%	153.8MiB / 320MiB
sentry-rca-clickhouse-1	62.88%	774.1MiB / 1.5GiB
sentry-rca-redpanda-1	23.60%	350.2MiB / 768MiB
-- target 125000, docker stats mid-step:
sentry-rca-processor-traces-1	51.18%	72.94MiB / 192MiB
sentry-rca-processor-metrics-1	99.57%	85.37MiB / 192MiB
sentry-rca-processor-logs-1	98.41%	68.09MiB / 192MiB
sentry-rca-otel-collector-1	1.52%	155.1MiB / 320MiB
sentry-rca-clickhouse-1	45.94%	799.5MiB / 1.5GiB
sentry-rca-redpanda-1	15.42%	353MiB / 768MiB

/sentry-rca-processor-metrics-1 restarts=0
/sentry-rca-processor-logs-1 restarts=0
/sentry-rca-processor-traces-1 restarts=0
```

**Ceiling: ~100,000 mixed events/s** sustained with bounded lag (177 messages ≈ 0.9 s at the end of the 100k step). Lag grows without bound from 125k (650 → 4,029 messages over two steps). **Bottleneck: CPU of the single-threaded Python processors** — metrics 99.6 % and logs 98.4 % of one core at 125k, ClickHouse ≤ 63 %, Redpanda ≤ 37 %, processor RSS ≤ 85 MiB, no restarts. The 50k step's `growing=True` is a false positive of the stop rule (124 messages of lag; the next step was clean). Upgrade path when it matters: more partitions and one processor replica per partition (consumer groups already allow it).

## M3b. Memory under load

Total RSS of the `sentry-rca-*` containers from the mid-step `docker stats` in the ceiling runs (M5):

```
run B (through the Collector), 80,000 events/s offered: 2,080.8 MiB over 16 containers
run D (direct into Redpanda), 100,000 events/s:        1,949.4 MiB over 16 containers
run D (direct into Redpanda), 125,000 events/s:        1,991.9 MiB over 16 containers
```

Phase 1 budget is 5 GB; the peak measured is 2.08 GB, leaving ~2.9 GB of the Phase 1 budget (and ~8.9 GB of the 11 GB whole-stack budget, SPEC §1.2) for Phase 3's local model.

## M3c. Memory with the other deploy-* stack stopped (2026-10-19, Phase 1 close-out)

Commands: `docker stop` on the 8 `deploy-*` containers; `tools/memory.sh` at idle (traffic stopped 90 s) and with demo traffic (120 s); under load from the mid-step `docker stats` of `uv run python tools/ceiling.py --direct --start 80000 --max 100000 --step-s 60 --procs 12 --batch 500`; then `docker start` on the same 8 containers.

```
## memory: idle, deploy-* stopped @ 2026-10-19T05:32:05Z
$ docker stats --no-stream (sentry-rca-*)
sentry-rca-alerting-1	32.4MiB / 160MiB	0.02%
sentry-rca-batchjob-1	45.73MiB / 128MiB	0.59%
sentry-rca-clickhouse-1	574.9MiB / 1.5GiB	11.15%
sentry-rca-demo-postgres-1	54.94MiB / 256MiB	0.11%
sentry-rca-gateway-1	53.96MiB / 256MiB	0.22%
sentry-rca-inventory-1	93.68MiB / 768MiB	0.58%
sentry-rca-orders-1	54.33MiB / 768MiB	0.25%
sentry-rca-otel-collector-1	129.4MiB / 320MiB	0.52%
sentry-rca-payments-1	50.67MiB / 768MiB	0.28%
sentry-rca-postgres-1	29.25MiB / 256MiB	0.00%
sentry-rca-processor-logs-1	50.94MiB / 192MiB	0.09%
sentry-rca-processor-metrics-1	38.95MiB / 192MiB	0.39%
sentry-rca-processor-traces-1	37.65MiB / 192MiB	0.10%
sentry-rca-redpanda-1	391.7MiB / 768MiB	0.87%
TOTAL	1717.2 MiB (15 containers)
$ docker run --rm alpine:3.20 free -m   (the Docker Desktop WSL2 VM)
              total        used        free      shared  buff/cache   available
Mem:           7751        2941        2460          62        2351        4557
Swap:          2048         273        1775
$ powershell (Get-CimInstance Win32_OperatingSystem) free/total physical memory (host)
host free 1,460 MiB of 16,004 MiB

## memory: normal demo traffic, deploy-* stopped @ 2026-10-19T05:34:14Z
$ docker stats --no-stream (sentry-rca-*)
sentry-rca-alerting-1	32.4MiB / 160MiB	0.01%
sentry-rca-archiver-1	0B / 0B	0.00%
sentry-rca-batchjob-1	45.73MiB / 128MiB	0.17%
sentry-rca-clickhouse-1	655.5MiB / 1.5GiB	21.38%
sentry-rca-demo-postgres-1	55.41MiB / 256MiB	5.34%
sentry-rca-gateway-1	54.79MiB / 256MiB	2.63%
sentry-rca-inventory-1	92.89MiB / 768MiB	2.52%
sentry-rca-orders-1	54.44MiB / 768MiB	3.43%
sentry-rca-otel-collector-1	121.1MiB / 320MiB	1.82%
sentry-rca-payments-1	50.67MiB / 768MiB	2.36%
sentry-rca-postgres-1	29.25MiB / 256MiB	4.94%
sentry-rca-processor-logs-1	50.95MiB / 192MiB	0.44%
sentry-rca-processor-metrics-1	38.95MiB / 192MiB	0.91%
sentry-rca-processor-traces-1	37.88MiB / 192MiB	0.79%
sentry-rca-redpanda-1	392.5MiB / 768MiB	10.47%
sentry-rca-traffic-1	21.87MiB / 96MiB	1.05%
TOTAL	1652.3 MiB (16 containers)
$ docker run --rm alpine:3.20 free -m   (the Docker Desktop WSL2 VM)
              total        used        free      shared  buff/cache   available
Mem:           7751        2970        2387          62        2394        4528
Swap:          2048         273        1775
$ powershell (Get-CimInstance Win32_OperatingSystem) free/total physical memory (host)
host free 1,577 MiB of 16,004 MiB

under load (sentry-rca-* RSS from mid-step docker stats):
  80,000 events/s (sent 78,612/s, lag end 86 msgs):  1,758.2 MiB over 16 containers
  100,000 events/s (sent 97,930/s, lag end 142 msgs): 1,802.9 MiB over 16 containers
  VM after the run: 
```

This stack: 1.65-1.72 GB at idle/normal, 1.80 GB under 100k events/s. With deploy-* stopped the Docker VM has 4.5 GB available (vs 3.0 GB with it running) and VM swap fell from 679 MB to 273 MB.

## M6. Overnight stall, 02:53-04:17 UTC (no fixture recorded for 84 minutes)

Three spurious incidents (02:58-03:12, 03:20-03:22, 03:33-03:35, 03:41) restarted the recorder's 15-minute quiet window repeatedly. No fixture was contaminated: the recorder refuses to inject until it has 15 quiet minutes. Measured contributors, all on the same laptop:

1. **Archiver crash loop from 01:11** (found at close-out): the running image predated the export fix and archived a whole day of spans with `FINAL`; ClickHouse killed it at its memory cap (code 241), Docker restarted it, it retried at once: 270 restarts, 57-59 failed queries per hour at 720-800 MiB each (`system.query_log`, exception_code 241). Fixed: days archived hour by hour (`recorder/archive.py`).
2. **My Phase 2 development runs** from ~02:52 (fixture-scale Python holding ~300k-row datasets in memory) while host free memory was ~600 MiB.
3. **OneDrive syncing** the new worktree and its .venv (0.9 cores sustained) until paused at ~03:35.

Together they pushed Windows to trim the Docker VM (vmmemWSL working set 5.3 -> 4.0 GB; VM swap 316 -> 679 MB), and every service slowed ~40% uniformly (gateway p95 71 -> ~100 ms) with stalls up to 1.5 s. It recovered after OneDrive was paused and apps closed (host free 0.8 -> 1.9-3.2 GB); the campaign resumed at 04:17 and finished at 05:19 with 19/19 fixtures, 0 failures.
