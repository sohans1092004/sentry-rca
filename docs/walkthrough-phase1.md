# Phase 1 walkthrough

Two journeys through the code, for a reader who did not write it:

1. one span, from a demo service to a ClickHouse row;
2. one injected failure, to an incident row and an `incidents.opened` message.

Every step names the file and line where it happens. Line numbers are for commit `main` at the
end of Phase 1.

---

## 1. A span: `POST /checkout` on gateway → a row in `spans`

A real row this produced (`SELECT ... FROM spans FINAL WHERE service='gateway' AND name='POST /checkout'`):

```
trace_id        af56b7e0549b934a7a46f7f930ef21f2
span_id         9bb36f31238a8c08
parent_span_id  (empty: the root of the trace)
service         gateway
name            POST /checkout
start_ts        2026-10-18 19:11:38.501
duration_ms     61.2
attrs           {span.kind: SERVER, http.route: /checkout, ...}
```

### 1.1 The service creates the span

- `services/gateway.py:10` builds the service through `Service("gateway")`, which calls
  `telemetry.setup` (`services/base.py:16`) and `telemetry.instrument` (`services/base.py:31`).
- `services/telemetry.py:65` `setup()` installs a `TracerProvider` whose `BatchSpanProcessor`
  exports over OTLP/HTTP every second (`services/telemetry.py:69`). The endpoint and the
  `x-sentry-service: gateway` header come from the container environment
  (`deploy/compose.yaml`, `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_HEADERS`).
- `services/telemetry.py:96` instruments the FastAPI app: every request gets a SERVER span named
  `METHOD route`. That is the span above, opened when the traffic generator calls `/checkout`
  (`services/gateway.py:26`).
- `services/telemetry.py:97` instruments httpx, so the call to orders
  (`services/gateway.py:17`) gets a CLIENT span and carries a W3C `traceparent` header; orders'
  FastAPI instrumentation continues the same trace. That is why one checkout trace contains spans
  from all four services (`tools/check_propagation.sh`, measurement M1).

### 1.2 The Collector receives, stamps and forwards it

`deploy/otel-collector.yaml`:

- `:7`: the OTLP/HTTP receiver keeps request headers as metadata, so `x-sentry-service` survives.
- `:14`–`:19`: `resource/tenant` **upserts** `sentry.tenant_id`. The tenant is decided by the
  server, never by the SDK; a spoofed value is overwritten.
- `:23`: the batch processor batches per `x-sentry-service` value, so each batch belongs to one
  service.
- `:29`–`:31`: the Kafka exporter writes the batch to `otel.traces.raw` with the record **key** set
  to that metadata value, so the key is literally `gateway` (SPEC C10).

### 1.3 The processor consumes, validates and writes it

`processors/runner.py`, the loop in `run()` (`:77`):

1. `:96` `consumer.consume(...)` takes up to 500 messages. Auto-commit is off
   (`:121`).
2. `:99` `process_batch` (`:55`) decodes each message. A protobuf decode error sends the whole
   message to the DLQ with its raw bytes (`:69`, envelope at `:31`).
3. Decoding calls `convert_traces` (`processors/convert.py:231`):
   - `_identity` (`processors/convert.py:89`) requires `service.name` and the Collector-set
     `sentry.tenant_id` (`processors/convert.py:24`). A resource without them is rejected whole.
   - `_span_rows` (`processors/convert.py:212`) checks every span: a 16-byte non-zero trace_id,
     an 8-byte span_id, an end not before its start, and so on. Each check goes through `_check`
     (`processors/convert.py:46`), and a failure rejects only that span
     (`processors/convert.py:102`). It records `span.kind` (`processors/convert.py:220`) because the
     `spans` table has no kind column.
4. `:101` `_insert` writes the batch to ClickHouse, with retries (`:43`).
5. `:103` invalid records are produced to `otel.traces.dlq` with their reason, then flushed.
6. `:109` **only now** are offsets committed. A kill at `:108` (the test crash point) redelivers
   the batch on restart. `test_kill_between_insert_and_commit_loses_nothing` proves no span goes
   missing, and the `commit_after_insert` guard check proves the test fails if the order is
   swapped.

### 1.4 ClickHouse stores it, and dedups a redelivery

- `common/migrations/clickhouse/0001_telemetry.sql:18`–`:24`: `spans` is a `ReplacingMergeTree`
  ordered by `(tenant_id, trace_id, span_id)`. A redelivered copy has the same key, so it collapses
  at merge time, and `FINAL` reads see one row. Metrics and logs have no natural ID, so the processor
  derives one from the record's content (`common/ids.py:10`, `:14`). The `stable_ids` guard check
  replaces that with `uuid4()` and the dedup test fails.
- `common/migrations/clickhouse/0002_views.sql:14`–`:16`: the `service_edges_mv` materialised view
  fires on the same insert. This span is SERVER, so it adds no edge. The gateway's CLIENT span
  to orders does: `gateway → orders`.

---

## 2. A failure: `pool_exhaustion` → an incident → `incidents.opened`

A real run (smoke test, seed 99): inventory's pool shrunk to 2 connections with every query held
196 ms, injected at 18:21:35.9 UTC; the incident opened at 18:21:48.3 (12.4 s later) on `gateway`,
absorbed 27 repeat alerts and auto-resolved 3 minutes after the last one.

### 2.1 The injector plans and injects it

- `injector/scenarios.py` `plan("pool_exhaustion", seed)` is pure: `random.Random(f"{scenario}:{variant}:{seed}")`
  picks the pool size, the hold time, the duration and the pre-injection delay. The same seed gives
  the same plan (`tests/unit/test_injector.py`).
- `injector/scenarios.py:158` `run()` waits the delay (`:160`), then POSTs the fault to inventory
  (`:186`) and records the exact time it was applied (`:188`). For `bad_deploy` it first writes the
  `deploys` row (`:178`). At the end it clears the fault (`:192`) and writes `runs/<run_id>.json`.

### 2.2 Inventory degrades; the failure travels upstream

- `services/faults.py:55`–`:58`: the service stores the fault with an expiry, so a crashed injector
  never leaves it broken.
- `services/demo_db.py:60`: every inventory query checks for `pool_exhaustion`. The pool is
  recreated at the small size, each query holds its connection an extra `query_delay_ms`
  (`services/demo_db.py:78`), and an acquire that waits past 0.5 s raises `PoolTimeout`
  (`services/demo_db.py:71`) → HTTP 503 and an ERROR log "pool acquire timeout".
- `services/payments.py`: payments confirms the hold with inventory before charging and retries
  failures 3 times (Amendment A2). That is the retry storm, and each attempt costs CPU (request
  signing). Orders gets 502s and slow responses, and so does the gateway. The traces carry the
  whole chain, because propagation is the same as in journey 1.

### 2.3 The metric reaches ClickHouse

- `services/telemetry.py:72`–`:73`: metrics are exported every 5 s with **delta** temporality
  (`:26`), so each point is "what happened in the last 5 s".
- `processors/convert.py:126`: a histogram point (`http.server.request.duration`) becomes `.count`,
  `.sum`, `.mean` and one `.bucket` row per bucket (`:139`, label `le` = upper bound). It travels the
  same path as the span: Collector → `otel.metrics.raw` → the metrics processor → `metrics`.

### 2.4 The Alert Engine decides

`alerting/engine.py`, `Engine.tick()` (`:159`), every 5 s (`:21`):

1. `:160` loads the enabled rules. The only seeded one is the gateway SLO rule
   (`common/migrations/postgres/0002_seed.sql`, Amendments A1/A8).
2. `:161` `read_window` (`:51`) queries ClickHouse with `FINAL`: 5xx counts for the last 60 s,
   bucket counts for the last 60 s (`:67`), and per-minute buckets for the 30 minutes before
   (`:72`).
3. `alerting/rules.py:46` `check()` evaluates `any_of`:
   - error rate (`:49`): 5xx / requests > 5 % with ≥ 20 requests, or
   - latency (`:54`): p95 from the buckets (`quantile_ms`, `:18`) as a robust z-score against the
     median and MAD of the baseline minutes (`robust_z`, `:37`), with the 1.5× and +20 ms floors.
   For this run the gateway's p95 jumped and the 5xx rate rose, and `check` returned the first breach.
4. `:165`–`:166`: the breach extends this rule's streak. The streak remembers when it began, which
   becomes `first_anomaly_at`. The rule needs 2 consecutive breaches (`consecutive` in the rule).
5. `:169` `record_alert` (`:86`) upserts the incident:
   `INSERT ... ON CONFLICT (tenant_id, fingerprint) WHERE status <> 'resolved' DO UPDATE SET
   last_seen = ..., alert_count = alert_count + 1` (`:99`). The conflict target is the partial
   unique index `incidents_one_open` (`common/migrations/postgres/0001_init.sql:16`). So the first
   breach pair **opens** the incident, and the next 26 evaluations only bump `alert_count`.
   `RETURNING (xmax = 0)` (`:101`) tells the engine whether this call inserted or updated.
6. `:172`–`:174`: only on open, `publish_opened` (`:116`) sends the event to `incidents.opened`,
   keyed `tenant_id:fingerprint` (`:120`), carrying `trigger_id = "opened:<incident_id>"` (`:41`).
   It flushes and raises if delivery failed.
7. `:176` `resolve_stale` marks it `resolved` once 3 minutes pass with no breach (`:22`).

### 2.5 Delivery is at least once, and redelivery is harmless

If the engine crashes after committing the incident but before publishing, the event would be
lost. Instead, `republish_open` (`alerting/engine.py:141`) republishes every non-resolved incident
on startup. The trigger id is deterministic, so a consumer that inserts on
`(incident_id, trigger_id)` with `ON CONFLICT DO NOTHING` (SPEC §6) sees one event however many
copies arrive: `test_incidents_opened_redelivery_is_one_event_downstream`. The
`stable_trigger_id` guard check makes the id random and that test fails.

### 2.6 The fixture recorder turns it into a dataset

`recorder/record.py` `record_one` does the same injection, then:

- waits for a quiet pre-window: no open incident and no activity for 15 min;
- counts incidents from the end of the quiet window, and rejects the fixture unless there is
  exactly one, starting after the fault;
- exports `first_anomaly_at − 15 min … last_seen + 5 min` (Amendment A7) to Parquet
  (`recorder/dataset.py`);
- builds gold claims from those rows and checks each against the SPEC §8.2 rule before writing
  it (`recorder/gold.py`);
- writes `label.json`, `injection.json` and `manifest.json` (row counts and content hashes), and
  registers the fixture in Postgres.

`recorder/load.py` loads a dataset into a fresh ClickHouse database and refuses it unless every
table's count and hash match the manifest (`test_fixture_round_trip_identical_counts_and_hashes`,
guard check `fixture_content_hash`).
