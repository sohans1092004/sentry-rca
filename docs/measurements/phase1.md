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
