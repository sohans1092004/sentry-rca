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
