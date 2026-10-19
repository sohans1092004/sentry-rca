# Phase 2 walkthrough: one incident, from `incidents.opened` to an outcome

For a reader who did not write the code. We follow `pool_exhaustion_001`: inventory's database pool
shrunk to one connection with every query held ~200 ms, so inventory times out, payments retries,
orders and the gateway slow down, and the gateway SLO rule opens an incident (Phase 1 walkthrough).
No LLM is involved anywhere below.

`rca show <investigation_id>` prints everything this walkthrough describes for a real investigation;
an example is at the end.

## 1. The trigger arrives

- `investigation/orchestrator.py:207` polls `incidents.opened` (published by the Alert Engine, keyed
  `tenant:fingerprint`, carrying `trigger_id = "opened:<incident_id>"`).
- `:211` `trigger()` (`:39`) inserts the investigation row with
  `ON CONFLICT (incident_id, trigger_id) DO NOTHING` (`:44`). A redelivered message finds the
  existing row and returns its id: one trigger, one investigation (§6, §15 row 4; guard
  `idempotent_investigation`). A new investigation moves the incident to `investigating` (`:49`).
- `:212` `acquire_slot()` takes one of two Postgres advisory-lock slots, so at most two
  investigations run at once across processes (§9). `:214` runs it; `:217` commits the Kafka offset
  only after the investigation is recorded.

The orchestrator connects as `sentry_app`, which may only INSERT and SELECT on the audit tables
(`common/migrations/postgres/0005_app_role.sql`; guard `append_only_grants`).

## 2. Scope, computed once

`investigate()` (`investigation/orchestrator.py:138`) first returns early if this ranker's result
already exists (`:149`), then computes the scope in `_scope()` (`:61`):

- if the row already holds a scope (a resumed investigation), it is reused (`:74`): the graph may
  have grown since, the scope must not;
- otherwise `investigation/scope.py:72` `compute()`: tenant from the incident row; window
  `first_anomaly_at − 30 min .. last_seen + 15 min` (`:74`), clamped to the fixture's recorded
  window in evals (`:75`, A7); services from `service_edges` over the last 24 h (`:77`) through a
  depth-2 BFS of the undirected graph (`allowed_services`, `:54`).

For `pool_exhaustion_001` the scope is `gateway, inventory, orders, payments`: `provider` is three hops
away, and nothing connects to the batch job. It is stored on the row (`orchestrator.py:78`).

## 3. The baseline asks questions; the tool layer answers, within scope

`investigation/run.py:38` gives the ranker a `ToolLayer` for this (investigation, ranker), and
`:39` runs `baseline.rank(scope, layer.call)`. Every question goes through
`investigation/tools.py:292` `ToolLayer.call`:

1. **Resume** (`:294`): if this ranker already made calls before a crash, the next call is answered
   from the persisted row instead of re-running (and a different request means the ranker is not
   deterministic: an error, not a silent divergence).
2. **Scope enforcement** (`:302` → `prepare()`, `:95`): unknown tools and arguments are rejected; a
   `tenant` argument other than the scope's is rejected (`:107`); every requested service must be in
   the allowlist (`_check_services`, `:56`); the window is clamped (`_window`, `:62`); `limit`/`top_k`
   are clamped (`_limit`, `:80`). Rejections are recorded with their reason and return an error
   result; clamps are recorded and the clamped request runs.
3. **Cache** (`:306`): an identical executed request in this investigation reuses the stored
   snapshot; the call is still audited.
4. **Fetch** (`:309` → `fetch()`, `:157`): the backend runs parameterised SQL with the tenant always
   bound (`investigation/backend.py`), returns at most 500 rows plus one to detect truncation, and
   every row gets its `row_id` (point_id, log_id, span_id, deploy id, or an ordinal for computed
   timeline rows).
5. **Snapshot, then audit, then return** (`:310`, `:316`): `investigation/snapshots.py:44` builds
   canonical JSON of `{tenant_id, rows, truncated}`, cuts it to 256 KB (`:51`), names it by its
   SHA-256 (`:56`); `PgStore.record` (`tools.py:227`) writes the zstd-compressed snapshot (`:234`)
   and the `tool_calls` row (`:236`) in one transaction. Only then are the rows, exactly as stored,
   returned to the ranker.

## 4. The baseline ranks (`investigation/baseline.py:152`)

For `pool_exhaustion_001` it made 21 tool calls:

1. `get_incident_timeline` (`:155`). The timeline (`investigation/timeline.py:75`) finds onsets per
   service and signal on 5 s export ticks (`:59`, threshold `:66`, two consecutive ticks `:69`): here
   inventory's latency, error rate and **pool wait** all jump at 21:25:26, and orders, payments and the
   gateway within half a second of it, so precedence alone cannot pick the cause.
2. Two trace queries from the first onset: slow traces (`:170`) and failing ones (`:179`).
   `_dominant()` (`:112`) walks each trace down from the gateway's root span along the failing or
   slowest child while it holds at least half the root's time; inventory is where the walk ends in
   most of them.
3. Per anomalous service, a fixed set of follow-ups: deploys (`:192`), WARN and ERROR logs (`:217`),
   memory or pool-wait metrics when those signals had onsets (`:233`, `:240`), latency (`:246`).
4. Kind evidence: inventory has `"pool acquire timeout"` log lines and a pool-wait rise, so its kind is
   `pool_exhaustion` (`:265`). Orders, payments and the gateway are only slow: `downstream_symptom`.
5. Claims: each hypothesis carries typed claims citing the rows used: `log_pattern` (`_log_claim`,
   `:87`), `metric_change` on pool wait and latency (`_metric_claim`, `:57`, threshold 0.8 × the rise
   the cited rows show), and `trace_dependency` gateway → inventory over the top five dominated traces
   (`:255`). Score `0.4 trace + 0.3 kind + 0.2 temporal + 0.1 deploy` (`:281`): inventory 0.662.

## 5. The verifier checks every claim (`investigation/verifier.py`)

`run.py:41` verifies each hypothesis against the stored calls only (`verify`, `verifier.py:217`):

- **Common checks** (`_cited`, `:72`): each cited `tool_call_seq` exists in this investigation, belongs
  to the same ranker, was not rejected, has a snapshot, and is the right tool for the claim type; every
  cited `row_id` is in that snapshot.
- **The claim's own check**, e.g. `metric_change` (`:99`): at least 3 cited rows in the 15-minute
  baseline and 3 in the window; `(w − b) / max(|b|, 1e-6)` (`:114`) at least the claimed magnitude.
- **Hypothesis rules**: at least one claim; a root cause needs more than `runbook_match` (`:225`); one
  failed claim rejects the hypothesis (`:227`), and every claim's result and reason are kept.

All four `pool_exhaustion_001` hypotheses pass.

## 6. The outcome, and what is stored

- `investigation/outcome.py:8`: no verified root cause → `INSUFFICIENT_EVIDENCE` (`:11`); two verified
  root causes for different (service, kind) within 0.1 → `CONFLICTING_EVIDENCE` (`:16`); otherwise
  `ROOT_CAUSE_IDENTIFIED`. Here: `ROOT_CAUSE_IDENTIFIED`, inventory / pool_exhaustion.
- `orchestrator.py:158` `_persist_hypotheses()` (`:82`) writes hypotheses (`:95`), claims (`:114`) and
  claim citations (`:133`) in one transaction, skipped if a previous run already committed them
  (`:86`). Then `investigation_results` (`:163`) and the investigation's status and outcome (`:168`).

Crash points sit between these steps (`:157`, `:159`); a killed investigation re-run reuses its tool
calls, skips the committed hypotheses and finishes without writing a duplicate row
(`tests/integration/test_phase2.py::test_killed_investigation_resumes_without_duplicating_rows`).

## Example `rca show` output

Eval run `af957445`, fixture `pool_exhaustion_001`, run 0 (long argument lists are cut at 120
characters by `rca show` itself):

```
$ uv run rca show f49c02c3-c42d-4946-bffe-bbe4dd956170
investigation f49c02c3-c42d-4946-bffe-bbe4dd956170  (incident f14c54fc-8a07-490c-89a7-3524b4182385 on gateway, first anomaly 2026-10-18 21:25:32.654520+00:00, trigger eval:af957445-30a8-4bf4-b092-834b3ca9da5b:0)
status complete  outcome ROOT_CAUSE_IDENTIFIED  budget {"wall_ms": 2266, "tool_calls": 21}
scope: tenant 00000000-0000-4000-8000-000000000001  services ['gateway', 'inventory', 'orders', 'payments']  window 2026-10-18T21:10:32.654Z .. 2026-10-18T21:35:47.635Z  caps 500 rows / 262144 B  excluded fixture pool_exhaustion_001

tool calls:
  #1   baseline get_incident_timeline  clamped    13 rows  202 ms  {"end": "2026-10-18T21:35:47.635Z", "services": ["gateway", "inventory", "orders", "payments"], "start": "2026  snapshot c6836324ee6a
  #2   baseline query_traces           allowed   444 rows  94 ms  {"end": "2026-10-18T21:28:26.073Z", "limit": 500, "min_duration_ms": 108.173, "services": ["gateway", "invento  snapshot 6770630c24e7
  #3   baseline query_traces           allowed   500 rows  78 ms  {"end": "2026-10-18T21:26:26.073Z", "limit": 500, "services": ["gateway", "inventory", "orders", "payments"],   snapshot 2a16bd917e4f
  #4   baseline get_recent_deploys     clamped     0 rows  0 ms  {"end": "2026-10-18T21:35:47.635Z", "service": "orders", "start": "2026-10-18T21:10:32.654Z"}  snapshot 95c16d5070a1
  #5   baseline query_logs             allowed     0 rows  63 ms  {"end": "2026-10-18T21:35:47.635Z", "limit": 500, "service": "orders", "severity": "WARN", "start": "2026-10-1  snapshot 95c16d5070a1
  #6   baseline query_logs             allowed   132 rows  61 ms  {"end": "2026-10-18T21:35:47.635Z", "limit": 500, "service": "orders", "severity": "ERROR", "start": "2026-10-  snapshot 6650595d1168
  #7   baseline query_metrics          clamped   500 rows  77 ms  {"end": "2026-10-18T21:35:47.635Z", "labels": {}, "metric": "http.server.request.duration.mean", "service": "o  snapshot ef36883c63b9
  #8   baseline get_recent_deploys     clamped     0 rows  46 ms  {"end": "2026-10-18T21:35:47.635Z", "service": "payments", "start": "2026-10-18T21:10:32.654Z"}  snapshot 95c16d5070a1
  #9   baseline query_logs             allowed     8 rows  62 ms  {"end": "2026-10-18T21:35:47.635Z", "limit": 500, "service": "payments", "severity": "WARN", "start": "2026-10  snapshot a4e487d558b8
  #10  baseline query_logs             allowed     0 rows  46 ms  {"end": "2026-10-18T21:35:47.635Z", "limit": 500, "service": "payments", "severity": "ERROR", "start": "2026-1  snapshot 95c16d5070a1
  #11  baseline query_metrics          clamped   303 rows  62 ms  {"end": "2026-10-18T21:35:47.635Z", "labels": {}, "metric": "http.server.request.duration.mean", "service": "p  snapshot 00576d444843
  #12  baseline get_recent_deploys     clamped     0 rows  47 ms  {"end": "2026-10-18T21:35:47.635Z", "service": "gateway", "start": "2026-10-18T21:10:32.654Z"}  snapshot 95c16d5070a1
  #13  baseline query_logs             allowed     0 rows  45 ms  {"end": "2026-10-18T21:35:47.635Z", "limit": 500, "service": "gateway", "severity": "WARN", "start": "2026-10-  snapshot 95c16d5070a1
  #14  baseline query_logs             allowed   132 rows  63 ms  {"end": "2026-10-18T21:35:47.635Z", "limit": 500, "service": "gateway", "severity": "ERROR", "start": "2026-10  snapshot 658cf0833942
  #15  baseline query_metrics          clamped   500 rows  61 ms  {"end": "2026-10-18T21:35:47.635Z", "labels": {}, "metric": "http.server.request.duration.mean", "service": "g  snapshot 1b7f1d76410b
  #16  baseline get_recent_deploys     clamped     0 rows  61 ms  {"end": "2026-10-18T21:35:47.635Z", "service": "inventory", "start": "2026-10-18T21:10:32.654Z"}  snapshot 95c16d5070a1
  #17  baseline query_logs             allowed     2 rows  63 ms  {"end": "2026-10-18T21:35:47.635Z", "limit": 500, "service": "inventory", "severity": "WARN", "start": "2026-1  snapshot 5cb25cad9ce8
  #18  baseline query_logs             allowed   140 rows  61 ms  {"end": "2026-10-18T21:35:47.635Z", "limit": 500, "service": "inventory", "severity": "ERROR", "start": "2026-  snapshot 82d299d62a70
  #19  baseline query_metrics          clamped   500 rows  62 ms  {"end": "2026-10-18T21:35:47.635Z", "labels": {}, "metric": "db.pool.wait.mean", "service": "inventory", "star  snapshot 17765ee969f7
  #20  baseline query_metrics          clamped   500 rows  62 ms  {"end": "2026-10-18T21:35:47.635Z", "labels": {}, "metric": "http.server.request.duration.mean", "service": "i  snapshot f8a16d3db163
  #21  baseline search_runbooks        allowed     3 rows  46 ms  {"query": "pool exhaustion in inventory", "top_k": 3}  snapshot ac90f555ef96

hypotheses:
  baseline #1 candidate_root_cause inventory:pool_exhaustion  score 0.6620  -> PASSED
      unverified explanation: inventory: pool_exhaustion evidence; dominant in 39 of 50 slow or failing traces.
      [passed] log_pattern {"min_count": 20, "pattern": "pool acquire timeout", "service": "inventory", "window": ["2026-10-18T
      [passed] metric_change {"direction": "up", "metric": "db.pool.wait.mean", "min_magnitude": 2172.3, "service": "inventory", 
      [passed] metric_change {"direction": "up", "metric": "http.server.request.duration.mean", "min_magnitude": 59.2, "service":
      [passed] trace_dependency {"child_service": "inventory", "min_latency_share": 0.96, "parent_service": "gateway"}
      [passed] runbook_match {"doc_id": "fa7600b9-e175-5196-9ddc-0cf78ff0eeab", "similarity": 0.7697}
  baseline #2 downstream_symptom orders:latency  score 0.2480  -> PASSED
      unverified explanation: orders slowed with no cause of its own in the evidence.
      [passed] metric_change {"direction": "up", "metric": "http.server.request.duration.mean", "min_magnitude": 13.9, "service":
      [passed] trace_dependency {"child_service": "orders", "min_latency_share": 0.97, "parent_service": "gateway"}
  baseline #3 downstream_symptom payments:latency  score 0.1900  -> PASSED
      unverified explanation: payments slowed with no cause of its own in the evidence.
      [passed] metric_change {"direction": "up", "metric": "http.server.request.duration.mean", "min_magnitude": 5.3, "service": 
      [passed] trace_dependency {"child_service": "payments", "min_latency_share": 0.5, "parent_service": "gateway"}
  baseline #4 downstream_symptom gateway:latency  score 0.1000  -> PASSED
      unverified explanation: gateway slowed with no cause of its own in the evidence.
      [passed] metric_change {"direction": "up", "metric": "http.server.request.duration.mean", "min_magnitude": 12.2, "service":
```
