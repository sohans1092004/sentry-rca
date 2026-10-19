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

## 4. The baseline ranks (`investigation/baseline.py:143`)

For `pool_exhaustion_001` it made 20 tool calls:

1. `get_incident_timeline` (`:146`). The timeline (`investigation/timeline.py:75`) finds onsets per
   service and signal on 5 s export ticks (`:59`, threshold `:66`, two consecutive ticks `:69`): here
   inventory's latency, error rate and **pool wait** all jump at 21:25:26, and orders, payments and the
   gateway within half a second of it, so precedence alone cannot pick the cause.
2. Two trace queries from the first onset: slow traces (`:161`) and failing ones (`:170`).
   `_dominant()` (`:103`) walks each trace down from the gateway's root span along the failing or
   slowest child while it holds at least half the root's time; inventory is where the walk ends in
   most of them.
3. Per anomalous service, a fixed set of follow-ups: deploys (`:183`), WARN and ERROR logs (`:207`),
   memory or pool-wait metrics when those signals had onsets (`:224`, `:231`), latency (`:237`).
4. Kind evidence: inventory has `"pool acquire timeout"` log lines and a pool-wait rise, so its kind is
   `pool_exhaustion` (`:256`). Orders, payments and the gateway are only slow: `downstream_symptom`.
5. Claims: each hypothesis carries typed claims citing the rows used: `log_pattern` (`_log_claim`,
   `:78`), `metric_change` on pool wait and latency (`_metric_claim`, `:48`, threshold 0.8 × the rise
   the cited rows show), and `trace_dependency` gateway → inventory over the top five dominated traces
   (`:246`). Score `0.4 trace + 0.3 kind + 0.2 temporal + 0.1 deploy` (`:272`): inventory 0.662.

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

Filled in from a real investigation of `pool_exhaustion_001` after the Phase 2 eval:
see `docs/measurements/phase2.md`.
