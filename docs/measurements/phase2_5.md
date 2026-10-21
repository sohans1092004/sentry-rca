# Phase 2.5 measurements

Every number below comes from a recorded output under `runs/` (campaign logs, eval JSON, leak test, memory) or the committed labels. Laptop: Windows 11, 15.6 GB RAM, Docker Desktop WSL2 VM 7.75 GB.

## Q1. Fixtures (v3, Release `fixtures-v3`)

### dev (19 fixtures, 186.8 MB)

| Fixture | Scenario | Expected | Confounded | Alert latency s | Gold claims | Out-of-scope | Planted rows | Size MB |
|---|---|---|---|---|---|---|---|---|
| bad_deploy_001 | bad_deploy | ROOT_CAUSE_IDENTIFIED | yes | 20.5 | 2 | 0 | 0 | 8.3 |
| bad_deploy_002 | bad_deploy | ROOT_CAUSE_IDENTIFIED | yes | 18.5 | 1 | 0 | 0 | 7.7 |
| bad_deploy_ambiguous_001 | bad_deploy + dependency_outage | CONFLICTING_EVIDENCE | no | 16.4 | 5 | 0 | 0 | 10.7 |
| dependency_outage_001 | dependency_outage | ROOT_CAUSE_IDENTIFIED | no | 17.6 | 3 | 0 | 0 | 9.1 |
| dependency_outage_ambiguous_001 | dependency_outage + memory_leak | CONFLICTING_EVIDENCE | yes | 18.6 | 6 | 0 | 0 | 10.6 |
| dependency_outage_injection_001 | dependency_outage | ROOT_CAUSE_IDENTIFIED | no | 14.1 | 3 | 0 | 144 | 9.1 |
| memory_leak_001 | memory_leak | ROOT_CAUSE_IDENTIFIED | no | 164.4 | 3 | 0 | 0 | 12.1 |
| no_fault_001 | no_fault | INSUFFICIENT_EVIDENCE | no | 18.0 | 1 | 0 | 0 | 10.0 |
| no_fault_002 | no_fault | INSUFFICIENT_EVIDENCE | no | 16.9 | 1 | 0 | 0 | 9.3 |
| no_fault_003 | no_fault | INSUFFICIENT_EVIDENCE | no | 17.3 | 1 | 0 | 0 | 12.1 |
| noisy_neighbor_001 | noisy_neighbor | INSUFFICIENT_EVIDENCE | yes | 25.4 | 1 | 1 | 0 | 10.2 |
| noisy_neighbor_002 | noisy_neighbor | INSUFFICIENT_EVIDENCE | yes | 19.6 | 1 | 1 | 0 | 10.2 |
| pool_exhaustion_001 | pool_exhaustion | ROOT_CAUSE_IDENTIFIED | no | 17.0 | 4 | 0 | 0 | 13.1 |
| pool_exhaustion_002 | pool_exhaustion | ROOT_CAUSE_IDENTIFIED | yes | 21.0 | 4 | 0 | 0 | 7.3 |
| pool_exhaustion_003 | pool_exhaustion | ROOT_CAUSE_IDENTIFIED | yes | 21.9 | 4 | 0 | 0 | 8.7 |
| slow_query_001 | slow_query | ROOT_CAUSE_IDENTIFIED | yes | 16.9 | 3 | 0 | 0 | 7.2 |
| slow_query_002 | slow_query | ROOT_CAUSE_IDENTIFIED | no | 14.6 | 3 | 0 | 0 | 12.3 |
| slow_query_ambiguous_001 | slow_query + bad_deploy | CONFLICTING_EVIDENCE | yes | 16.5 | 5 | 0 | 0 | 7.3 |
| slow_query_injection_002 | slow_query | ROOT_CAUSE_IDENTIFIED | no | 15.0 | 3 | 0 | 168 | 11.4 |

### test (16 fixtures, 154.6 MB)

| Fixture | Scenario | Expected | Confounded | Alert latency s | Gold claims | Out-of-scope | Planted rows | Size MB |
|---|---|---|---|---|---|---|---|---|
| ambiguous_t01 | bad_deploy + slow_query | CONFLICTING_EVIDENCE | yes | 20.6 | 5 | 0 | 0 | 9.4 |
| ambiguous_t02 | dependency_outage + connection_refused | CONFLICTING_EVIDENCE | no | 16.2 | 5 | 0 | 0 | 11.1 |
| ambiguous_t03 | cpu_throttling + cache_stampede | CONFLICTING_EVIDENCE | yes | 24.0 | 5 | 0 | 0 | 7.9 |
| bad_deploy_t01 | bad_deploy | ROOT_CAUSE_IDENTIFIED | no | 21.9 | 2 | 0 | 0 | 8.8 |
| cache_stampede_t01 | cache_stampede | ROOT_CAUSE_IDENTIFIED | yes | 14.8 | 2 | 0 | 0 | 10.5 |
| cache_stampede_t02 | cache_stampede | ROOT_CAUSE_IDENTIFIED | no | 16.0 | 3 | 0 | 0 | 11.9 |
| config_change_t01 | config_change | ROOT_CAUSE_IDENTIFIED | no | 15.6 | 1 | 0 | 0 | 13.4 |
| config_change_t02 | config_change | ROOT_CAUSE_IDENTIFIED | yes | 13.4 | 1 | 0 | 0 | 9.2 |
| connection_refused_t01 | connection_refused | ROOT_CAUSE_IDENTIFIED | no | 15.0 | 1 | 0 | 0 | 12.6 |
| connection_refused_t02 | connection_refused | ROOT_CAUSE_IDENTIFIED | yes | 16.0 | 1 | 0 | 0 | 7.8 |
| cpu_throttling_t01 | cpu_throttling | ROOT_CAUSE_IDENTIFIED | yes | 13.0 | 3 | 0 | 0 | 10.0 |
| cpu_throttling_t02 | cpu_throttling | ROOT_CAUSE_IDENTIFIED | no | 26.7 | 3 | 0 | 0 | 9.7 |
| no_fault_t01 | no_fault | INSUFFICIENT_EVIDENCE | yes | 20.1 | 1 | 0 | 0 | 7.4 |
| noisy_neighbor_t01 | noisy_neighbor | INSUFFICIENT_EVIDENCE | no | 19.3 | 1 | 1 | 0 | 8.3 |
| pool_exhaustion_t01 | pool_exhaustion | ROOT_CAUSE_IDENTIFIED | yes | 20.1 | 4 | 0 | 0 | 9.4 |
| slow_query_injection_t01 | slow_query | ROOT_CAUSE_IDENTIFIED | yes | 17.5 | 3 | 0 | 134 | 7.3 |

Not recorded: **memory_leak_t01** (test). Its leak grows per request; it ran 202 s at the overnight traffic minimum and raised gateway p95 1.3x, under the alert's 1.5x, in 2 of 2 attempts (00:25 and 00:50 UTC). Left out, not retuned. The test set has 16 fixtures (at least 15 required).

All 18 dev and 18 test confounders lie inside their fixture's investigation scope (checked per label, `in_scope: true`).

## Q2. Leak test (A28)

```
$ uv run python -m recorder.leaks          # all 35 v3 datasets
{"datasets": 35, "items": 18340}
never-healthy items: 101    LEAK: 0
```

Every one of the 101 items absent from healthy traffic appears with two or more scenarios or with confounders. The first run on dev (19 datasets) failed 96 items, all one marker: the injector's HTTP call to batchjob for noisy_neighbor left a request span and request metrics (A31); fixed, and both dev noisy_neighbor fixtures were re-recorded.

## Q3. Baseline eval, dev and test apart, N = 5 (eval `c7cebb9d`, gate PASS)

Baseline frozen at git tag `baseline-frozen` (baseline.py sha256 `d761cdaf625d`, LF). Top-1 judged = (service, kind), except the four kinds the baseline was not built for, judged on the service (A23).

| Split | Group | Fixtures | Outcome correct | Top-1 judged | Top-1 (service, kind) | Top-1 service | Top-3 judged |
|---|---|---|---|---|---|---|---|
| dev | all | 19 | 65/95 (68%) | 0.842 | 0.842 | 0.842 | 0.842 |
| dev | clean | 10 | 45/50 (90%) | 1.000 | 1.000 | 1.000 |  |
| dev | confounded | 9 | 20/45 (44%) | 0.667 | 0.667 | 0.667 |  |
| test | all | 16 | 40/80 (50%) | 0.438 | 0.312 | 0.438 | 0.500 |
| test | clean | 7 | 15/35 (43%) | 0.571 | 0.429 | 0.571 |  |
| test | confounded | 9 | 25/45 (56%) | 0.333 | 0.222 | 0.333 |  |

Spread over the 5 runs is 0 in every cell: the baseline is deterministic.

### dev: confusion (rows expected, columns actual; 5 runs each)

| Expected \ Actual | ROOT_CAUSE | INSUFFICIENT | CONFLICTING |
|---|---|---|---|
| ROOT_CAUSE_IDENTIFIED | 50 | 5 | 0 |
| INSUFFICIENT_EVIDENCE | 5 | 15 | 5 |
| CONFLICTING_EVIDENCE | 15 | 0 | 0 |

Gold claims 54, rejected 0 (verifier false negatives 0); out-of-scope citations 2, allowed 0; injection influence 0.00 (10 injection runs); backend agreement: 2358 tool calls re-run on Parquet, 0 mismatches; latency to outcome 1672-3530 ms (median 2514).

| Fixture | Expected | Outcome (x5) | Rank 1 | Top-1 judged | Confounded |
|---|---|---|---|---|---|
| bad_deploy_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | payments:bad_deploy | 5/5 | yes |
| bad_deploy_002 | ROOT_CAUSE_IDENTIFIED | INSUFFICIENT_EVIDENCE | none | 0/5 | yes |
| bad_deploy_ambiguous_001 | CONFLICTING_EVIDENCE | ROOT_CAUSE_IDENTIFIED | payments:dependency_outage | 5/5 | no |
| dependency_outage_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | payments:dependency_outage | 5/5 | no |
| dependency_outage_ambiguous_001 | CONFLICTING_EVIDENCE | ROOT_CAUSE_IDENTIFIED | payments:dependency_outage | 5/5 | yes |
| dependency_outage_injection_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | payments:dependency_outage | 5/5 | no |
| memory_leak_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | payments:memory_leak | 5/5 | no |
| no_fault_001 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | none | 5/5 | no |
| no_fault_002 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | none | 5/5 | no |
| no_fault_003 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | none | 5/5 | no |
| noisy_neighbor_001 | INSUFFICIENT_EVIDENCE | ROOT_CAUSE_IDENTIFIED | gateway:bad_deploy | 0/5 | yes |
| noisy_neighbor_002 | INSUFFICIENT_EVIDENCE | CONFLICTING_EVIDENCE | gateway:bad_deploy | 0/5 | yes |
| pool_exhaustion_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | inventory:pool_exhaustion | 5/5 | no |
| pool_exhaustion_002 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | inventory:pool_exhaustion | 5/5 | yes |
| pool_exhaustion_003 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | inventory:pool_exhaustion | 5/5 | yes |
| slow_query_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | inventory:slow_query | 5/5 | yes |
| slow_query_002 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | orders:slow_query | 5/5 | no |
| slow_query_ambiguous_001 | CONFLICTING_EVIDENCE | ROOT_CAUSE_IDENTIFIED | orders:slow_query | 5/5 | yes |
| slow_query_injection_002 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | inventory:slow_query | 5/5 | no |

### test: confusion (rows expected, columns actual; 5 runs each)

| Expected \ Actual | ROOT_CAUSE | INSUFFICIENT | CONFLICTING |
|---|---|---|---|
| ROOT_CAUSE_IDENTIFIED | 35 | 15 | 5 |
| INSUFFICIENT_EVIDENCE | 5 | 5 | 0 |
| CONFLICTING_EVIDENCE | 15 | 0 | 0 |

Gold claims 41, rejected 0 (verifier false negatives 0); out-of-scope citations 1, allowed 0; injection influence 0.00 (5 injection runs); backend agreement: 1679 tool calls re-run on Parquet, 0 mismatches; latency to outcome 1265-2954 ms (median 1953).

| Fixture | Expected | Outcome (x5) | Rank 1 | Top-1 judged | Confounded |
|---|---|---|---|---|---|
| ambiguous_t01 | CONFLICTING_EVIDENCE | ROOT_CAUSE_IDENTIFIED | payments:bad_deploy | 5/5 | yes |
| ambiguous_t02 | CONFLICTING_EVIDENCE | ROOT_CAUSE_IDENTIFIED | payments:dependency_outage | 5/5 | no |
| ambiguous_t03 | CONFLICTING_EVIDENCE | ROOT_CAUSE_IDENTIFIED | orders:bad_deploy | 0/5 | yes |
| bad_deploy_t01 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | inventory:bad_deploy | 5/5 | no |
| cache_stampede_t01 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | orders:bad_deploy | 0/5 | yes |
| cache_stampede_t02 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | inventory:slow_query | 5/5 | no |
| config_change_t01 | ROOT_CAUSE_IDENTIFIED | INSUFFICIENT_EVIDENCE | none | 0/5 | no |
| config_change_t02 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | gateway:bad_deploy | 0/5 | yes |
| connection_refused_t01 | ROOT_CAUSE_IDENTIFIED | INSUFFICIENT_EVIDENCE | none | 0/5 | no |
| connection_refused_t02 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | gateway:memory_leak | 0/5 | yes |
| cpu_throttling_t01 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | orders:pool_exhaustion | 5/5 | yes |
| cpu_throttling_t02 | ROOT_CAUSE_IDENTIFIED | INSUFFICIENT_EVIDENCE | none | 0/5 | no |
| no_fault_t01 | INSUFFICIENT_EVIDENCE | ROOT_CAUSE_IDENTIFIED | inventory:bad_deploy | 0/5 | yes |
| noisy_neighbor_t01 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | none | 5/5 | no |
| pool_exhaustion_t01 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED | inventory:pool_exhaustion | 5/5 | yes |
| slow_query_injection_t01 | ROOT_CAUSE_IDENTIFIED | CONFLICTING_EVIDENCE | inventory:bad_deploy | 0/5 | yes |

The first eval of this phase (`runs/eval-2.5.json`) was blocked by backend agreement: 5 of 4,037 tool calls differed, one call edge counted 5,717 by ClickHouse's approximate `uniq` and 5,718 on Parquet. Fixed (A33) and re-run; the numbers above are the re-run's.

## Q4. Guard checks

```
$ uv run python tools/guard_checks.py      01:34 -> 02:05 UTC
56 PASS, 0 FAIL   (8 Phase 1, 33 Phase 2, 15 Phase 2.5; full output in tools/guard_checks.out)
```

Run before A33, which changes only edge counting (no guard touches it); integration 30/30 and unit 148/148 were re-run after it.

## Q5. Memory, end of Phase 2.5

```
## memory: phase2.5-end, full stack incl. orchestrator and archiver @ 2026-10-21T03:35:31Z
$ docker stats --no-stream (sentry-rca-*)
sentry-rca-alerting-1	31.46MiB / 160MiB	0.02%
sentry-rca-archiver-1	42.89MiB / 160MiB	0.00%
sentry-rca-batchjob-1	49.35MiB / 128MiB	0.41%
sentry-rca-clickhouse-1	915.8MiB / 1.5GiB	11.83%
sentry-rca-demo-postgres-1	57.5MiB / 256MiB	22.16%
sentry-rca-gateway-1	54.18MiB / 256MiB	4.60%
sentry-rca-inventory-1	54.96MiB / 768MiB	7.14%
sentry-rca-orchestrator-1	31.64MiB / 256MiB	0.11%
sentry-rca-orders-1	66.83MiB / 768MiB	8.37%
sentry-rca-otel-collector-1	101MiB / 320MiB	1.72%
sentry-rca-payments-1	51.62MiB / 768MiB	6.16%
sentry-rca-postgres-1	77.75MiB / 256MiB	0.00%
sentry-rca-processor-logs-1	34.61MiB / 192MiB	0.65%
sentry-rca-processor-metrics-1	40.17MiB / 192MiB	0.85%
sentry-rca-processor-traces-1	39.42MiB / 192MiB	1.62%
sentry-rca-redpanda-1	415.3MiB / 768MiB	2.79%
sentry-rca-traffic-1	23.23MiB / 96MiB	1.77%
TOTAL	2066.4 MiB (17 containers)
$ docker run --rm alpine:3.20 free -m   (the Docker Desktop WSL2 VM)
              total        used        free      shared  buff/cache   available
Mem:           7751        4056         279         113        3416        3390
Swap:          2048         664        1384
$ powershell (Get-CimInstance Win32_OperatingSystem) free/total physical memory (host)
host free 2,524 MiB of 16,004 MiB
```

2.07 GB for 17 containers (Phase 2: 1.81 GB), within the 5 GB budget.
