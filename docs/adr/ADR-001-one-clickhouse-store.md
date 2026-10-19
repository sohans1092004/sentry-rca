# ADR-001: Metrics, logs and traces in one ClickHouse store

**Status:** Draft (Phase 1). Parts marked TODO wait for Phase 2/4 measurements.

## Context

Sentry-RCA needs three telemetry shapes: time-series points (alerting, `metric_change` claims), log
lines (substring search for `log_pattern` claims) and spans (parent/child walks for
`trace_dependency` claims and the dependency graph). Everything runs on one laptop with a memory
budget (SPEC §1.2: ≤ 11 GB including the local model; ≤ 5 GB for the Phase 1 stack). Ingestion is
at-least-once (ADR-003), so the store must make duplicates harmless.

The usual production split is a TSDB (Prometheus/Mimir) + a log store (Loki/Elasticsearch) + a
trace store (Tempo/Jaeger): three query languages, three retention configs, three processes.

## Decision

One ClickHouse server holds `metrics`, `logs` and `spans` (SPEC §4.1), each a `ReplacingMergeTree`
whose sorting key ends in a stable ID (`point_id`, `log_id`, `(trace_id, span_id)`), with a 7-day TTL.
Two materialised views derive `service_edges` (from CLIENT spans) and `metrics_1h` (1-hour
downsample, 90 days).

## Consequences

- **One query language and one join surface.** The alert engine, the recorder and (Phase 2) the
  tools all speak SQL against one database; an investigation can correlate a metric step with the
  logs and spans of the same window in one place, and an eval loads a fixture into one isolated
  database (`recorder/load.py`).
- **Dedup is a read-time cost.** Redelivered rows collapse only at merge time, so exact reads use
  `FINAL`. Measured so far: the alert engine queries with `FINAL` every 5 s.
  TODO (§19 decision 7): measure `FINAL` vs `argMax` per tool on fixture-sized data in Phase 2.
  Measured in Phase 1: `FINAL` over `spans` with a time filter cannot prune (the sorting key starts
  with `trace_id`), so it merges every part while reading. On a 38M-row table that ran the server out
  of memory (code 241, 843 MiB of a 1.02 GiB cap). Deduplicating only the window's rows with
  `LIMIT 1 BY <stable key>` needed ~130 MiB. The recorder uses that, and Phase 2 tools on `spans`
  should too, or a time-ordered projection should be added.
- **Insert-time optimisation is a trap in tests.** `optimize_on_insert` collapses duplicates inside
  one insert block, so "both copies physically stored" is false for a single batch; the dedup test
  delivers copies in separate batches too (bug log, Phase 1 report).
- **Materialised views see pre-dedup data.** `metrics_1h.sum_value/points` over-count a redelivered
  batch's hour; `avg/min/max` do not change. Accepted at this scale (`ponytail:` note in
  `0002_views.sql`).
- **`service_edges` is derived from one span, not a join.** A plain MV only sees the inserted block,
  so the edge comes from each CLIENT span's `peer.service`/`server.address`. Edges therefore depend
  on client instrumentation naming its callee.
- **Memory.** ClickHouse is capped at 1.1 GB server memory (`deploy/clickhouse/memory.xml`), system
  logs are off. Measured RSS: see `docs/measurements/phase1.md`.

## When this would flip

- Trace volume diverging from metrics by orders of magnitude (tail-based sampling, a dedicated trace
  store with columnar span storage and its own retention).
- Full-text needs beyond substring match (relevance ranking, tokenised search across months): a
  search engine for logs.
- TODO: record the label cardinality at which tool-query latency degrades (SPEC §17 "ClickHouse
  query latency"), Phase 4.
