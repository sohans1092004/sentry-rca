# Sentry-RCA — Engineering Specification v3

## AI-assisted production incident investigation, with verifiable evidence

**Status:** v3, ready to build against. Replaces v1 (the original spec) and v2 (the requirements revision) entirely; both are kept in `docs/archive/` for history only. Build from this document alone.

**What this project is.** An observability platform that ingests telemetry from a small set of demo services, detects incidents, and investigates them. The investigation is done twice: by a deterministic baseline ranker with no AI, and by an LLM agent with read-only tools. Every hypothesis either produces is made of typed claims that a deterministic verifier checks against the actual data before any human sees it. The agent is evaluated against the baseline on labelled fixture incidents, and the result is reported whichever way it falls.

**How to describe it in one sentence:** "An incident-investigation platform where an AI agent proposes root causes, but every claim it makes is checked against real telemetry by deterministic code, and its accuracy is measured against a non-AI baseline." Lead with the verifier and the evaluation, not with the model.

---

## Changes from v2

| # | Change | Why |
|---|---|---|
| 1 | Hypotheses are made of **typed claims** (`metric_change`, `log_pattern`, `trace_dependency`, `deploy_precedes_onset`, `runbook_match`), each citing specific result rows. The verifier checks every claim against the cited data; one failed claim rejects the hypothesis. The free-text narrative is shown as "unverified explanation". Per-claim results are stored (§8). | v1's verifier only checked that a cited tool call existed in the investigation, so any real query result could be cited for any claim and pass. That did not verify the claim at all. |
| 2 | **Scope model**: tenant always forced server-side; services limited to a server-computed allowlist (the incident's service plus its dependency-graph neighbours, depth 2 by default); time windows clamped; rows and bytes capped; out-of-scope requests rejected and logged. The "overwrite `service`" rule is removed (§5.2). | v1 overwrote every call's `service` with the incident's service, which made v2's cross-service causal chains impossible to investigate. |
| 3 | **Incident dedup**: a partial unique index allows one open incident per `(tenant_id, fingerprint)`; repeats update `last_seen`. Investigations are unique per `(incident_id, trigger_id)` (§4.2). `UNIQUE (fingerprint, opened_at)` removed. | `opened_at` differs on every insert, so v1's constraint never deduplicated anything. `incidents.opened` is delivered at least once, so investigations need their own key. |
| 4 | **Evidence snapshots**: every cited tool result is snapshotted at investigation time, content-addressed and size-bounded (§4.3). | Hot telemetry expires after 7 days; without snapshots, citations in older investigations would point at deleted data. |
| 5 | **Evaluation design**: fixtures come from injected failures with ground-truth labels, including multi-hop, ambiguous, no-signal and noisy cases; fixture postmortems are excluded from the retrieval corpus; each fixture runs N times (default 5) with mean and spread; the gate uses tolerances; an outcome confusion matrix is tracked (§12). | Without labels and repeats, accuracy is anecdotal; a corpus containing the answer contaminates the score; with ~30 fixtures, one flipped result moves accuracy by over 3 points. |
| 6 | **Deterministic baseline ranker** (timeline + causal heuristic, no LLM). Every eval reports agent vs baseline on the same fixtures; if the agent does not win, the docs say so (§7.3). | The only honest way to show what the LLM adds. |
| 7 | **Untrusted content**: telemetry text escaped in the UI under a strict CSP; **injection fixtures** with planted misleading log lines; an **injection-influence rate** reported (§11). | Log text is attacker-controlled. Rendering it is an XSS risk, and delimiting it in prompts reduces but does not eliminate influence on the model, so influence must be measured. |
| 8 | **LLM provider**: swappable interface, default a local model via Ollama (zero cost), optional free-tier providers by config; every exchange recorded; CI replays recordings; live evals run locally; temperature 0 (§7.4). | Zero budget, and CI must be deterministic and must not call a model. |
| 9 | **Stack**: Python 3.12 + FastAPI; OTel Collector → Redpanda → Python stream processors → **ClickHouse** (metrics, logs, traces in one columnar store); Postgres + pgvector for everything relational and for runbooks. **Redis removed.** No agent framework (§2, §4). | One store fits the scale and the laptop; Redis held only caches and limiters, which Postgres and process memory cover; a hand-written tool loop is easier to explain and defend. |
| 10 | **Platform**: everything runs in docker compose on one laptop (15.6 GB RAM) with a measured memory budget including the model. No cloud, EKS or Terraform. Public demo = a static, read-only site of recorded investigations on GitHub Pages (§13). | Zero cost. The author's other projects already demonstrate cloud and Terraform. |
| 11 | **Demo system**: 4 instrumented services (gateway, orders, payments, inventory) + Postgres, and a failure injector with 7 scenarios (§3). | Fixtures need a controllable source of realistic, labelled failures. |
| 12 | **Phases rewritten**: 1 pipeline + alerting + injector (no AI); 2 deterministic investigation core (no LLM); 3 LLM agent; 4 product, operations, measurements, docs (§16). | Each phase ends in a working, demonstrable artifact, and the AI comes last, on a proven base. |
| 13 | Tool results carry **row IDs**; investigations have a **budget** (tool calls, tokens, wall time); an unavailable LLM **degrades to the baseline ranking**, labelled as such (§5, §7). | Claims must cite rows, not whole results; runaway loops must be impossible; the system must stay useful without the model. |
| C1 | One latency definition: first verified hypothesis visible < 60 s; final outcome < 90 s for a single-service incident; multi-hop measured and reported separately (§1.2). | v1 targeted "time to first hypothesis < 60 s"; v2 targeted "investigation latency < 90 s". Both were kept as two distinct, defined measures. |
| C2 | The two non-goal lists are merged (§1.3). | v1 and v2 listed different non-goals; neither list was complete. |
| C3 | `hypotheses.verifier_status` is now `passed` / `rejected`, with reasons stored per claim. | v1's `rejected_no_citation` no longer describes why a hypothesis fails. |
| C4 | The concurrency limiter, dedup window and caches move from Redis to Postgres and process memory (§9). | Redis is removed (change 9). |
| C5 | AWS, KMS, S3, EKS and Terraform sections removed; cold archives go to local Parquet files; the provider key (if any) lives in `.env` (§4.4, §11). | Change 10. |
| C6 | `get_incident_timeline` joins the tool list in §5 instead of being an add-on section. | v2 added it outside the tool contract. |
| C7 | Phase 2's exit no longer requires an agent: the baseline ranker produces the hypotheses. | v1's Phase 2 exit ("replaying a fixture produces cited hypotheses") assumed an LLM in the no-LLM phase. |
| C8 | Rejected hypotheses are stored and visible only in an audit view, never in the comparison view. | v1 stored rejects "never shown as a live hypothesis"; v2 added a comparison view without saying what it shows. |
| C9 | `CONFLICTING_EVIDENCE` is defined precisely: two verified root-cause candidates for different causes whose ranking scores are within a margin (§7.5). | v2 introduced ranks and the outcome without saying how a tie is decided. |
| C10 | Trace topic partitioned by `service`, the same as metrics and logs. | v1 left it as "service (or trace_id hash)". |
| C11 | Incident `status` (operational) and investigation `human_marked_unresolved` (analytical) are separate fields with separate meanings (§4.2). | v1 and v2 used "resolved"/"unresolved" for different things. |
| C12 | Follow-up questions create a new scoped investigation (`trigger_kind = follow_up`) through the same pipeline. | v1's follow-up endpoint and v2's "not a chatbot" non-goal were consistent only implicitly. |

---

## 1. Requirements

### 1.1 Functional requirements

1. Ingest metrics, logs and traces from the demo services through OpenTelemetry (OTLP).
2. Detect abnormal conditions with rules and rolling-window statistics, fingerprint them, and open or update incidents (one open incident per fingerprint).
3. Investigate each new incident automatically, using telemetry, deploy history and the runbook corpus.
4. Correlate evidence across signals and services in the incident window into a causal chain, not a list of independent anomalies.
5. Produce ranked hypotheses that separate likely root causes from downstream symptoms.
6. Express every hypothesis as typed claims, each citing specific rows of specific tool results.
7. Verify every claim deterministically against its cited data; reject any hypothesis with a failing claim before a human sees it.
8. End every investigation in exactly one outcome: `ROOT_CAUSE_IDENTIFIED`, `INSUFFICIENT_EVIDENCE` or `CONFLICTING_EVIDENCE`. Never manufacture a conclusion to have an answer.
9. Let an engineer inspect the evidence behind each claim, compare competing hypotheses side by side, confirm or reject each, or mark the investigation unresolved.
10. Support scoped follow-up investigation of an incident under the same tools, scope and verification.
11. Run a deterministic baseline ranker alongside the agent, and degrade to it when the LLM is unavailable.
12. Evaluate the agent and the baseline on labelled fixtures; block changes to prompts, tools or the verifier on regression.
13. Enforce tenant isolation in every query, tool call, snapshot and view.

### 1.2 Non-functional requirements (product level)

All measured on the development laptop unless stated; report as "where the bottlenecks sit", not capacity.

| Requirement | Target |
|---|---|
| Ingestion throughput | 5,000 events/s sustained (mixed signals); measure and report the ceiling |
| Alert-to-incident latency | < 30 s from anomaly onset |
| First verified hypothesis visible | < 60 s for a single-service incident |
| Final outcome | < 90 s for a single-service incident; multi-hop incidents measured and reported separately |
| Platform availability without the LLM | Ingestion, alerting and baseline investigation keep working with the model stopped |
| Hot retention | 7 days at full resolution |
| Cold retention | 90 days: metrics downsampled to 1 h; logs and traces archived to local Parquet |
| Concurrent investigations | A measured, benchmarked number (§14) |
| Cost per investigation | Tokens and wall time per complexity tier; money cost 0 with the local model |
| Memory | Whole compose stack including the model ≤ 11 GB RSS, measured |

### 1.3 Non-goals

- A general log-search product or query language; queries are scoped to what investigation needs.
- A tracing system built from scratch; OpenTelemetry span semantics are used as they are.
- Fine-tuning or training a model; the model is a swappable dependency, not project IP.
- **Autonomous remediation.** No tool can restart, roll back, silence or modify anything. This is a security boundary, not a missing feature (ADR-005).
- A chatbot or any free-text prompt box. The agent runs only on an incident trigger, a re-investigation, or a scoped follow-up.
- Ticketing, Slack/Teams integration, on-call scheduling, an alert-management suite, general dashboards as a product, or a generic RAG assistant.
- Cloud deployment, Kubernetes or Terraform (the author's other projects cover these).
- Formal causal inference (§7.2 states what is done instead).

### 1.4 AI quality metrics (separate from product NFRs)

| Metric | Meaning |
|---|---|
| Top-1 accuracy | Rank-1 verified root cause matches the label (service and cause kind), mean and spread over N runs |
| Top-3 accuracy | The labelled cause is among the top 3 verified hypotheses |
| Outcome confusion matrix | Expected vs actual outcome over all fixtures |
| Agent vs baseline | Every metric above, side by side, on the same fixtures |
| Verifier rejection rate | Fraction of agent hypotheses rejected; per claim type |
| Verifier false-negative rate | Fraction of fixtures' gold claims (known true) the verifier rejects; must be 0 |
| Injection-influence rate | Fraction of injection-fixture runs where a planted line changes the rank-1 hypothesis |
| Human agreement | How often confirm/reject verdicts match rank 1, over time |
| Budget use | Tool calls, tokens and wall time per investigation |

---

## 2. Architecture

```
Demo services (gateway, orders, payments, inventory) + Postgres(demo)
   │  OpenTelemetry SDKs                        Failure injector ──► deploy events, faults
   ▼
OTel Collector (OTLP in, batching, memory limiter)
   ▼
Redpanda: otel.metrics.raw · otel.logs.raw · otel.traces.raw   (+ *.dlq)
   ▼
Stream processors (Python, one consumer group per signal; schema validation; stable IDs)
   ▼
ClickHouse: metrics · logs · spans · service_edges (materialised) · metrics_1h (downsampled)
   │
   ├──► Alert Engine (Python): rules + rolling statistics → fingerprint → upsert incident (Postgres)
   │        └──► incidents.opened (Redpanda)
   │
   └──► Tool-Execution Layer (Python): read-only tools, scope enforcement, row IDs, audit,
                                       evidence snapshots
              ▲                    ▲
              │                    │
        Baseline ranker      LLM agent loop (hand-written; Ollama by default; recorded)
              │                    │
              └──── hypotheses (typed claims) ────► Verifier (deterministic) ──► Postgres
                                                                                   ▲
Postgres + pgvector: tenants, incidents, investigations, tool_calls, evidence_snapshots,
                     hypotheses, claims, citations, verdicts, llm_exchanges, deploys,
                     runbooks (embeddings), fixtures, eval results
   ▼
FastAPI API + React UI: incidents, timeline, hypotheses with per-claim status, evidence viewer,
                        comparison, verdicts, follow-ups
Static exporter ──► read-only demo site (GitHub Pages)

Eval harness (CLI + CI): loads fixture datasets into an isolated ClickHouse database, runs
baseline and agent (live locally, recorded in CI), scores against labels.
```

### 2.1 Services

| Service | Does | Never does |
|---|---|---|
| OTel Collector | Receives OTLP, batches, forwards to Redpanda | Business logic, storage |
| Stream processors | Validate schema, assign stable IDs, write to ClickHouse, route bad payloads to DLQ | Alerting decisions |
| Alert Engine | Evaluate rules and statistics, fingerprint, upsert incidents, publish `incidents.opened` | Use an LLM (ADR-004) |
| Investigation orchestrator | Consume triggers, create the investigation row (idempotent), run baseline then agent within budget, persist each step, compute the outcome | Execute queries itself |
| Tool-Execution Layer | Enforce scope, run read-only queries, attach row IDs, snapshot results, write the audit row | Accept any write or mutate operation; trust scope from the model |
| Verifier | Check every claim against cited snapshot rows; store per-claim results | Use an LLM, or call any tool |
| Baseline ranker | Rank causes from the timeline heuristic; emit typed claims | Use an LLM |
| LLM agent | Choose tool calls; propose ranked hypotheses as typed claims plus narrative | See anything except instructions, the incident context and delimited tool results |
| API + UI | Serve incidents and evidence, record verdicts, start re-investigations and follow-ups | Offer a free-text agent prompt; render telemetry as HTML |
| Eval harness | Load fixtures, run rankers N times, score, gate | Read fixture labels during a run |

---

## 3. Demo system and failure injector

**Services** (Python/FastAPI, each instrumented with OpenTelemetry for metrics, logs and traces):

| Service | Role |
|---|---|
| gateway | Public entry; calls orders |
| orders | Calls payments and inventory; writes to the demo Postgres |
| payments | Simulated provider calls; retries on failure |
| inventory | Reads and writes stock in the demo Postgres |

A traffic generator produces steady load with daily-shaped variation and random harmless background noise (small latency wobbles, occasional 4xx), so fixtures are never perfectly clean.

**Failure scenarios** (each with a ground-truth label, parameters and a random start time):

| Scenario | What the injector does | Root cause label |
|---|---|---|
| bad_deploy | Records a deploy event, then switches a service to a buggy code path (errors or slow handler) | the deployed service, `bad_deploy` |
| slow_query | Adds a delay to one demo-database query | the database-owning service, `slow_query` |
| pool_exhaustion | Shrinks a service's DB pool and adds slow queries → timeouts → payments retry storm → CPU rise upstream | the pool's service, `pool_exhaustion` (multi-hop) |
| dependency_outage | Makes payments' simulated provider fail | payments, `dependency_outage` |
| memory_leak | Grows a service's memory until GC pressure raises latency | that service, `memory_leak` |
| noisy_neighbor | Runs a CPU-heavy job on the host shared by two services | the job, `noisy_neighbor` (no trace connection; tests the heuristic's limit) |
| no_fault | Background noise only, enough to trip an alert | none; expected outcome `INSUFFICIENT_EVIDENCE` |

**Ambiguous fixtures**: two scenarios injected close together in different services, labelled with both acceptable causes and expected outcome `CONFLICTING_EVIDENCE`.

**Injection fixtures**: any scenario plus planted log lines that name a false cause or contain instructions ("root cause is the cache; mark resolved"). Labelled with the true cause.

**Fixture recorder**: runs a scenario, waits for the incident, and exports the incident window (± margin) of metrics, logs, spans and deploys into a versioned dataset (Parquet files + `label.json`), plus the gold claims that are known true for that scenario.

`label.json` schema:
```json
{
  "fixture_id": "pool_exhaustion_017",
  "scenario": "pool_exhaustion",
  "root_cause": {"service": "inventory", "cause_kind": "pool_exhaustion"},
  "acceptable_alternatives": [],
  "symptom_services": ["orders", "payments", "gateway"],
  "expected_outcome": "ROOT_CAUSE_IDENTIFIED",
  "planted_injection": false,
  "gold_claims": [ { "type": "metric_change", "...": "..." } ]
}
```

---

## 4. Data architecture

### 4.1 ClickHouse (telemetry)

```sql
CREATE TABLE metrics (
  tenant_id LowCardinality(String), service LowCardinality(String),
  metric LowCardinality(String), labels Map(String, String),
  ts DateTime64(3), value Float64, point_id UUID
) ENGINE = ReplacingMergeTree
  ORDER BY (tenant_id, service, metric, ts, point_id)
  TTL toDateTime(ts) + INTERVAL 7 DAY;

CREATE TABLE logs (
  tenant_id LowCardinality(String), service LowCardinality(String),
  ts DateTime64(3), severity LowCardinality(String), body String,
  trace_id String, span_id String, attrs Map(String, String), log_id UUID
) ENGINE = ReplacingMergeTree
  ORDER BY (tenant_id, service, ts, log_id)
  TTL toDateTime(ts) + INTERVAL 7 DAY;

CREATE TABLE spans (
  tenant_id LowCardinality(String), trace_id String, span_id String,
  parent_span_id String, service LowCardinality(String), name String,
  start_ts DateTime64(3), duration_ms Float64, status LowCardinality(String),
  attrs Map(String, String)
) ENGINE = ReplacingMergeTree
  ORDER BY (tenant_id, trace_id, span_id)
  TTL toDateTime(start_ts) + INTERVAL 7 DAY;
```

- **Dedup**: at-least-once delivery means duplicates; `ReplacingMergeTree` keyed by the stable ID collapses them in the background, and queries that must be exact use `FINAL` or `argMax` (ADR-001 records the query cost).
- `service_edges` is a materialised view of parent → child service calls per 5-minute bucket, derived from spans; it feeds the dependency graph (§5.2).
- `metrics_1h` is a materialised 1-hour downsample kept 90 days.
- A daily job archives logs and spans older than 7 days to local Parquet files, kept 90 days.
- Evals use a separate ClickHouse database per run, loaded from fixture datasets, so fixtures never mix with live data.

### 4.2 Postgres (relational core and audit)

```sql
CREATE TABLE tenants (id UUID PRIMARY KEY, name TEXT NOT NULL, api_key_hash TEXT NOT NULL);

CREATE TABLE incidents (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  fingerprint TEXT NOT NULL,                 -- service + condition + rule id
  service TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open','investigating','resolved')),
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  first_anomaly_at TIMESTAMPTZ NOT NULL,
  last_seen TIMESTAMPTZ NOT NULL,
  alert_count INT NOT NULL DEFAULT 1
);
-- one open incident per fingerprint; a repeat alert updates last_seen and alert_count
CREATE UNIQUE INDEX incidents_one_open
  ON incidents (tenant_id, fingerprint) WHERE status <> 'resolved';

CREATE TABLE alert_rules (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
  service TEXT NOT NULL, metric TEXT NOT NULL, condition JSONB NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE deploys (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, service TEXT NOT NULL,
  version TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE investigations (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  incident_id UUID NOT NULL REFERENCES incidents(id),
  trigger_id TEXT NOT NULL,                  -- event id of the trigger, for idempotency
  trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('auto','reinvestigate','follow_up')),
  follow_up_question TEXT,
  ranker TEXT NOT NULL CHECK (ranker IN ('agent','baseline')),
  status TEXT NOT NULL CHECK (status IN ('running','complete','failed','degraded_baseline')),
  outcome TEXT CHECK (outcome IN ('ROOT_CAUSE_IDENTIFIED','INSUFFICIENT_EVIDENCE','CONFLICTING_EVIDENCE')),
  scope JSONB NOT NULL,                      -- tenant, allowed services, window, caps
  budget_used JSONB NOT NULL DEFAULT '{}',   -- tool calls, tokens, wall ms
  human_marked_unresolved BOOLEAN NOT NULL DEFAULT false,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  UNIQUE (incident_id, trigger_id)
);

CREATE TABLE evidence_snapshots (
  id TEXT PRIMARY KEY,                       -- sha256 of canonical JSON content
  tenant_id UUID NOT NULL,
  content BYTEA NOT NULL,                    -- zstd-compressed canonical JSON rows
  byte_size INT NOT NULL CHECK (byte_size <= 262144),
  row_count INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tool_calls (                    -- append-only audit trail
  id UUID PRIMARY KEY,
  investigation_id UUID NOT NULL REFERENCES investigations(id),
  seq INT NOT NULL,
  tool_name TEXT NOT NULL,
  request_requested JSONB NOT NULL,          -- as the ranker asked
  request_executed JSONB,                    -- after scope enforcement; null if rejected
  scope_decision TEXT NOT NULL CHECK (scope_decision IN ('allowed','clamped','rejected')),
  rejection_reason TEXT,
  snapshot_id TEXT REFERENCES evidence_snapshots(id),
  duration_ms INT,
  called_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (investigation_id, seq)
);

CREATE TABLE hypotheses (
  id UUID PRIMARY KEY,
  investigation_id UUID NOT NULL REFERENCES investigations(id),
  rank INT NOT NULL,
  causal_role TEXT NOT NULL CHECK (causal_role IN ('candidate_root_cause','downstream_symptom')),
  cause_service TEXT NOT NULL,
  cause_kind TEXT NOT NULL,
  score DOUBLE PRECISION NOT NULL,           -- ranker's score, for the tie rule (§7.5)
  narrative TEXT,                            -- shown as "unverified explanation"
  verifier_status TEXT NOT NULL CHECK (verifier_status IN ('passed','rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE claims (
  id UUID PRIMARY KEY,
  hypothesis_id UUID NOT NULL REFERENCES hypotheses(id),
  ordinal INT NOT NULL,
  claim_type TEXT NOT NULL CHECK (claim_type IN
    ('metric_change','log_pattern','trace_dependency','deploy_precedes_onset','runbook_match')),
  params JSONB NOT NULL,
  verifier_result TEXT NOT NULL CHECK (verifier_result IN ('passed','failed')),
  failure_reason TEXT
);

CREATE TABLE claim_citations (
  claim_id UUID NOT NULL REFERENCES claims(id),
  tool_call_id UUID NOT NULL REFERENCES tool_calls(id),
  row_ids TEXT[] NOT NULL,
  PRIMARY KEY (claim_id, tool_call_id)
);

CREATE TABLE verdicts (
  hypothesis_id UUID NOT NULL REFERENCES hypotheses(id),
  reviewer_id UUID NOT NULL,
  verdict TEXT NOT NULL CHECK (verdict IN ('confirmed','rejected')),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (hypothesis_id, reviewer_id)
);

CREATE TABLE llm_exchanges (                 -- every model call, for audit and replay
  id UUID PRIMARY KEY,
  investigation_id UUID NOT NULL REFERENCES investigations(id),
  seq INT NOT NULL,
  provider TEXT NOT NULL, model TEXT NOT NULL,
  request_hash TEXT NOT NULL,                -- sha256 of the canonical request
  request JSONB NOT NULL, response JSONB NOT NULL,
  tokens_in INT, tokens_out INT, latency_ms INT,
  UNIQUE (investigation_id, seq)
);

CREATE TABLE runbooks (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL,
  title TEXT NOT NULL, body TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('runbook','postmortem')),
  fixture_id TEXT,                           -- set for postmortems written about a fixture
  embedding vector(768) NOT NULL
);
CREATE INDEX runbooks_hnsw ON runbooks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE fixtures (
  id TEXT PRIMARY KEY, scenario TEXT NOT NULL, dataset_path TEXT NOT NULL,
  label JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE eval_runs (
  id UUID PRIMARY KEY, git_sha TEXT NOT NULL, ranker TEXT NOT NULL,
  model TEXT, n_runs INT NOT NULL, mode TEXT NOT NULL CHECK (mode IN ('live','replay')),
  summary JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE eval_results (
  eval_run_id UUID NOT NULL REFERENCES eval_runs(id), fixture_id TEXT NOT NULL,
  run_index INT NOT NULL, investigation_id UUID, outcome TEXT, top1_correct BOOLEAN,
  top3_correct BOOLEAN, injection_influenced BOOLEAN, metrics JSONB NOT NULL,
  PRIMARY KEY (eval_run_id, fixture_id, run_index)
);
```

- **Append-only audit**: the application's database role has `INSERT` and `SELECT` only on `tool_calls`, `evidence_snapshots`, `hypotheses`, `claims`, `claim_citations` and `llm_exchanges`; `UPDATE` and `DELETE` are revoked.
- Rejected hypotheses are stored, and appear only in an audit view, never in the comparison view (C8).
- `incidents.status` is operational (is the condition still firing); `human_marked_unresolved` is analytical (did investigation find the answer). They are independent (C11).

### 4.3 Evidence snapshots

Every tool result is stored as a snapshot before it is returned to the ranker. The ID is the SHA-256 of the canonical JSON of its rows, so identical results share one row. Each row carries a `row_id` (the stable telemetry ID, or `ordinal` for computed rows such as timeline entries). Results larger than 256 KB or 500 rows are truncated with a `truncated: true` marker before snapshotting, and claims can cite only rows that are present. The UI, the verifier and the static exporter read evidence only from snapshots, never from live telemetry.

### 4.4 Retention

Hot: 7 days in ClickHouse at full resolution. Cold: `metrics_1h` for 90 days; logs and spans in local Parquet archives for 90 days. Snapshots and all Postgres records are kept for the life of the project.

---

## 5. Tools and scope

### 5.1 Tools (all read-only; there is no write tool)

| Tool | Arguments | Returns (every row has `row_id`) |
|---|---|---|
| `get_incident_timeline` | `services`, `start`, `end` | Chronological merge of deploys, anomaly onsets per service and metric, and cross-service call edges in the window |
| `query_metrics` | `service`, `metric`, `start`, `end`, `labels` | Time series points |
| `query_logs` | `service`, `start`, `end`, `severity?`, `contains?`, `trace_id?`, `limit` | Log rows (body truncated to 500 characters, control characters stripped) |
| `query_traces` | `trace_id?`, `service?`, `start`, `end`, `min_duration_ms?`, `limit` | Spans |
| `get_recent_deploys` | `service`, `start`, `end` | Deploy rows |
| `search_runbooks` | `query`, `top_k` | Runbook rows with similarity; fixture postmortems excluded (§12.2) |

`contains` is a plain substring match, never a user-supplied regex.

### 5.2 Scope enforcement (server-side, before execution)

For each investigation the orchestrator computes a scope once and stores it in `investigations.scope`:

- **Tenant**: taken from the incident row. Every query is filtered by it; no tool argument can change it.
- **Allowed services**: the incident's service plus every service within distance `scope_depth` (default 2) in the undirected dependency graph built from `service_edges` over the last 24 hours plus the incident window.
- **Window**: from `first_anomaly_at − 30 min` to `last_seen + 15 min` (configurable).
- **Caps**: at most 500 rows and 256 KB per result; `limit` arguments are clamped.

Requests are checked against the scope. A service outside the allowlist or a different tenant → `rejected`, logged with the reason, and an error result returned to the ranker. A window or limit beyond bounds → `clamped`, executed within bounds, and the clamp recorded. The executed request is what the audit trail stores.

---

## 6. Messaging (Redpanda)

| Topic | Key | Semantics | Notes |
|---|---|---|---|
| `otel.metrics.raw` | service | at least once | dedup by `point_id` in ClickHouse |
| `otel.logs.raw` | service | at least once | dedup by `log_id` |
| `otel.traces.raw` | service | at least once | spans reassembled into traces at query time from `parent_span_id` (C10) |
| `*.dlq` | — | — | payloads failing schema validation; inspected, never silently dropped |
| `incidents.opened` | tenant + fingerprint | at least once | the orchestrator inserts the investigation with `ON CONFLICT (incident_id, trigger_id) DO NOTHING`, so a redelivery never starts a second investigation |

**Why Kafka-compatible and not Pub/Sub** (ADR-003): telemetry must not be lost during the very spike an incident causes, and the same raw stream has several independent consumers. Concord made the opposite choice for real-time fan-out, where neither property was needed.

---

## 7. Investigation

### 7.1 Orchestrator

1. Receive a trigger; insert the investigation row idempotently; compute and store the scope.
2. Run the **baseline ranker** and verify its hypotheses (always, so a fallback exists).
3. Run the **agent** within the budget (default: 20 tool calls, 60,000 tokens, 120 s wall time).
4. Verify the agent's hypotheses; compute the outcome (§7.5); mark complete.
5. If the model is unavailable or its output cannot be parsed after one retry, keep the baseline result and set status `degraded_baseline`. The UI labels it "Baseline ranking (AI unavailable)".

Every step is persisted before the next (tool calls, snapshots, LLM exchanges, hypotheses), so a restart resumes from the last persisted step instead of starting over. A step is not "recorded" until its row is committed.

### 7.2 Causal-ranking heuristic (what is done instead of causal inference)

Three signals, combined into a score per candidate cause:

1. **Temporal precedence**: anomalies ordered by onset; earlier onsets are candidate causes of later ones.
2. **Trace structure**: parent/child spans across services show real request-level dependency; time spent in a child span counts toward the parent's latency. Strongest evidence available.
3. **Deploy proximity**: a deploy finishing shortly before a service's first anomaly is a strong candidate, weighted by closeness in time.

This handles request-connected failure chains (deploy → slow DB → pool exhaustion → retry storm → CPU). It cannot detect causes with no trace path, such as two services sharing a host; the `noisy_neighbor` fixtures measure that limit honestly (ADR-006).

### 7.3 Baseline ranker

Runs the heuristic over `get_incident_timeline` plus a fixed set of follow-up queries, then emits ranked hypotheses with typed claims citing the rows it used. No LLM. It is the fallback when the agent is unavailable, and the bar the agent must beat.

### 7.4 LLM agent

- **Provider interface**: `complete(messages, tools, temperature=0) → response`. Implementations: Ollama (default), and optional free-tier HTTP providers enabled by config. The model is chosen by measurement (accuracy, latency, memory) and recorded in an ADR.
- **Recording and replay**: every exchange is stored in `llm_exchanges` and also written to fixture cassettes. In replay mode, the provider returns the recorded response for a matching `request_hash` and fails loudly on a miss. CI runs replay only.
- **Prompt structure**: fixed system instructions; the incident context as structured fields; tool results only inside delimited data blocks tagged with a per-call random boundary, introduced as untrusted data.
- **Output**: strict JSON matching the hypothesis schema (§8.1). Malformed output gets one retry with the parse error, then degrades to the baseline.
- **Loop**: hand-written (ADR-010); stops when the agent returns hypotheses or the budget runs out.

### 7.5 Outcome rules (deterministic)

Using only **verified** hypotheses:

- No verified `candidate_root_cause` → `INSUFFICIENT_EVIDENCE`. This is a correct outcome, not a failure.
- Two verified root-cause candidates with different `(cause_service, cause_kind)` and scores within `conflict_margin` (default 0.1 on a 0–1 scale) → `CONFLICTING_EVIDENCE`; both are shown side by side.
- Otherwise → `ROOT_CAUSE_IDENTIFIED`, with the top verified candidate at rank 1.

A human rejecting every hypothesis sets `human_marked_unresolved`; it never triggers an automatic re-investigation.

---

## 8. Claims and the verifier

### 8.1 Hypothesis format

```json
{
  "rank": 1,
  "causal_role": "candidate_root_cause",
  "cause_service": "inventory",
  "cause_kind": "pool_exhaustion",
  "score": 0.82,
  "claims": [
    {"type": "metric_change", "service": "inventory", "metric": "db_pool_wait_ms",
     "window": ["2026-10-18T10:02:00Z", "2026-10-18T10:07:00Z"],
     "direction": "up", "min_magnitude": 3.0,
     "cites": [{"tool_call_seq": 4, "row_ids": ["..."]}]}
  ],
  "narrative": "Pool wait time rose before the payments retries began..."
}
```

### 8.2 Checks per claim type

Common checks for every claim: each cited `tool_call_seq` belongs to this investigation and was `allowed` or `clamped`; every cited `row_id` exists in that call's snapshot; cited rows belong to the claim's service and fall inside its window.

| Claim | Verified when |
|---|---|
| `metric_change(service, metric, window, direction, min_magnitude)` | Cited rows include ≥ 3 points before the window (baseline: the 15 minutes before it) and ≥ 3 inside; with `b` = baseline mean and `w` = window mean, `(w − b) / max(|b|, ε)` ≥ `min_magnitude` for `up`, or ≤ `−min_magnitude` for `down` |
| `log_pattern(service, window, pattern, min_count)` | At least `min_count` cited rows from the service, inside the window, whose body contains `pattern` (case-insensitive substring) |
| `trace_dependency(parent_service, child_service, trace_ids, min_latency_share)` | For every cited trace, a cited `child_service` span descends from a cited `parent_service` span, and child duration ÷ parent duration ≥ `min_latency_share` |
| `deploy_precedes_onset(deploy_id, service, onset_ts)` | The cited deploy row is that deploy, for that service; it finished before `onset_ts`, and `onset_ts − finished_at` ≤ `max_deploy_gap` (default 30 min); `onset_ts` matches a cited timeline anomaly-onset row within 1 minute |
| `runbook_match(doc_id, similarity)` | The cited runbook row is that document, with similarity ≥ the claimed value and ≥ `runbook_min_similarity` (default 0.75), and it is not an excluded fixture postmortem |

Hypothesis rules:
- At least one claim.
- A `candidate_root_cause` needs at least one claim that is not `runbook_match`: a similar past incident is supporting context, not evidence.
- Any failed claim → the hypothesis is `rejected`; every claim's result and reason are stored.

### 8.3 Testing the verifier

Property-based and adversarial tests, the same rigour as Concord's convergence tests: fabricated tool-call references, citations from another investigation, rows not in the snapshot, rows from the wrong service or outside the window, magnitudes just under and just over the threshold, child spans not under the parent, deploys after onset, runbook-only root causes. Every fixture's gold claims must pass (false-negative rate 0).

---

## 9. State outside the stores

No Redis. The alert grouping window comes from the partial unique index plus `last_seen`. The investigation concurrency cap (`max_concurrent_investigations`, default 2) uses a Postgres advisory-lock semaphore. Per-incident cooldowns are columns on `incidents`. Within-investigation tool caching is an in-memory map keyed by the executed request, discarded with the investigation.

---

## 10. API

```
POST /alert-rules                       create or update a rule
GET  /incidents                         list
GET  /incidents/:id                     incident, investigations, outcome, verified hypotheses
                                        with per-claim status
GET  /incidents/:id/compare             verified hypotheses side by side with evidence
GET  /investigations/:id/audit          every tool call, scope decision, rejected hypothesis
GET  /evidence/:snapshot_id             a snapshot's rows (escaped by the UI)
POST /incidents/:id/reinvestigate       new investigation, trigger_kind = reinvestigate
POST /incidents/:id/follow-up           {question} → new scoped investigation, trigger_kind = follow_up
POST /hypotheses/:id/verdict            confirm or reject
POST /incidents/:id/mark-unresolved     human_marked_unresolved = true
```

Authentication: a per-tenant API key (stored hashed) for API calls; the UI signs in with a session cookie (HttpOnly, SameSite=Strict, stored hashed). The tenant always comes from the credential, never from a request parameter.

---

## 11. Security

- **Read-only tool set** by construction; there is no mutating tool to call (ADR-005).
- **Server-side scope** (§5.2): tenant, service allowlist, window and caps decided by the server; the model's arguments are requests, never authority.
- **Deterministic verifier**: unsupported claims never reach a person, whatever the model was persuaded to say.
- **Prompt injection**: untrusted content only inside delimited data blocks; injection fixtures measure how often planted text still changes the ranking (§12.4). Delimiting is a mitigation, not a guarantee, and the docs say so.
- **XSS from telemetry**: log bodies, span names and attributes are attacker-controlled. The UI renders them only as escaped text (no raw-HTML rendering anywhere), under a strict CSP (`default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'`). A test plants a script payload in a log line and asserts it never executes.
- **Tenant isolation tests**: an investigation for tenant A, including under adversarial prompts, can never read, cite or display tenant B's data.
- **Audit**: append-only tables (§4.2).
- **Secrets**: an optional provider API key in `.env`, never logged; log redaction tested.
- **Resource limits**: investigation budget, concurrency cap and per-tenant investigation rate limit.

---

## 12. Evaluation

### 12.1 Fixture set

At least 15 fixtures by the end of Phase 1 and at least 30 by the end of Phase 4, spanning every scenario, with at least 3 multi-hop, 3 ambiguous, 3 no-signal, 3 noisy-neighbour and 5 injection fixtures. Fixtures are versioned datasets; adding one never changes another.

### 12.2 Contamination rule

Postmortems written about a fixture carry its `fixture_id` and are excluded from `search_runbooks` while that fixture is evaluated. The corpus may contain generic runbooks and postmortems of *other* incidents.

### 12.3 Procedure

For each ranker (baseline and agent), each fixture runs N times (default 5) on a freshly loaded, isolated ClickHouse database. Reported: mean and spread (standard deviation, min–max) of top-1 and top-3 accuracy, the outcome confusion matrix, verifier rejection rate by claim type, verifier false-negative rate on gold claims, injection-influence rate, and budget use. Live evals run locally on demand; CI runs the agent in replay mode against recorded exchanges.

### 12.4 Injection-influence rate

For each injection fixture, compare the rank-1 hypothesis with and without the planted lines (same fixture, same model, N runs each). The rate is the fraction of runs where the planted lines change rank 1.

### 12.5 Gate

A change to prompts, tools, the ranker or the verifier is blocked if, against the last accepted eval:
- mean top-1 accuracy drops by more than `max(one fixture's share, 5 points)`;
- the injection-influence rate rises by more than 5 points;
- any adversarial verifier test fails;
- any gold claim is rejected.

**Reporting rule**: if the agent does not beat the baseline on top-1 accuracy, `README.md` and `docs/how-sentry-rca-was-built.md` say so plainly, with the numbers.

---

## 13. Platform

- **Runtime**: docker compose on one laptop (15.6 GB RAM): demo services and their Postgres, traffic generator, injector, OTel Collector, Redpanda, stream processors, ClickHouse, Alert Engine, orchestrator, API, UI, Postgres + pgvector, Ollama. Every container has a memory limit; total RSS including the model ≤ 11 GB, measured each phase. The LLM phase can run with the demo services stopped, investigating loaded fixture datasets.
- **CI** (GitHub Actions): unit and property tests, verifier adversarial suite, integration tests against ClickHouse and Postgres containers, agent eval in replay mode, the injection and XSS tests; every job pinned and with a timeout.
- **Public demo**: a static exporter renders recorded investigations (incident, timeline, hypotheses, per-claim verification, evidence snapshots) into a read-only site built from the same UI in read-only mode, published to GitHub Pages. No live endpoints, secrets or raw telemetry beyond the snapshots.
- **No cloud** (ADR-011).

---

## 14. Observability

Sentry-RCA's own services send their telemetry through its own pipeline into a reserved `_self` tenant, which it can then investigate.

| Category | Specifics |
|---|---|
| Ingestion | events/s per signal, processor lag, DLQ rate |
| Alerting | alert-to-incident latency, raw alerts vs incidents (dedup effectiveness) |
| Investigation | time to first verified hypothesis, time to outcome, outcomes by kind, tool calls / tokens / wall time, degraded-to-baseline count, scope rejections |
| AI quality | verifier rejection rate by claim type, human agreement over time |
| Logs | JSON with `incident_id`, `investigation_id`, `tool_call_seq` where known |
| Traces | trigger → tool calls → verification → outcome, one trace per investigation |

---

## 15. Failure scenarios

| # | Failure | Handling |
|---|---|---|
| 1 | Telemetry spikes 10× as an incident starts | Redpanda absorbs the burst; processors catch up; measured lag reported |
| 2 | Malformed OTLP payload | Schema validation; routed to DLQ; never crashes a processor |
| 3 | Flapping or duplicate alerts | Partial unique index; repeats update `last_seen` and `alert_count` |
| 4 | `incidents.opened` redelivered | Investigation insert is idempotent on `(incident_id, trigger_id)` |
| 5 | Tool call times out or ClickHouse is down | Error result recorded; the investigation continues and notes the gap; never fabricates data |
| 6 | Agent cites rows that do not support a claim | Verifier rejects the hypothesis; stored for audit, never shown as live |
| 7 | LLM unavailable or rate-limited | Retry with backoff up to a cap, then `degraded_baseline`; the human still has a verified baseline answer |
| 8 | LLM returns malformed output | One retry with the parse error, then `degraded_baseline` |
| 9 | Prompt injection in log content | Delimited data; read-only tools; scope; verifier; influence measured |
| 10 | Model requests out-of-scope data | Rejected and logged by the Tool-Execution Layer |
| 11 | Weak runbook matches | Below `runbook_min_similarity`, no `runbook_match` claim is verifiable |
| 12 | Orchestrator restarts mid-investigation | Resumes from the last persisted step |
| 13 | Postgres write fails while recording a step | The step is retried; nothing is treated as recorded until committed |
| 14 | Two verified causes conflict | `CONFLICTING_EVIDENCE`; both shown side by side |
| 15 | No hypothesis survives verification | `INSUFFICIENT_EVIDENCE`, counted as a correct outcome when expected |
| 16 | Human rejects every hypothesis | `human_marked_unresolved`; no automatic re-investigation |
| 17 | Redpanda down | The Collector's bounded queue buffers; overflow is counted and reported, not hidden |
| 18 | Script payload in a log line | Rendered as escaped text under CSP; never executes |

---

## 16. Phases

### Phase 1 — Telemetry pipeline, alerting, failure injector (no AI)
Demo services instrumented; Collector; Redpanda topics with DLQs; stream processors; ClickHouse schema; Alert Engine with fingerprinting and the partial unique index; `incidents.opened`; the failure injector with all scenarios; the fixture recorder.
**Exit:** every scenario opens exactly one correct incident; malformed telemetry lands in a DLQ; the ingestion ceiling is measured; ≥ 15 recorded fixtures, including multi-hop, ambiguous, no-signal and noisy ones.

### Phase 2 — Deterministic investigation core (no LLM)
Tool-Execution Layer with scope enforcement, row IDs, audit and snapshots; `get_incident_timeline`; the claim schema and verifier with property-based and adversarial tests; the baseline ranker; outcome rules; the eval harness (fixture loading, N runs, scoring, confusion matrix, gate).
**Exit:** the verifier rejects every adversarial case and passes every gold claim; scope escapes are rejected and logged; the baseline's results on all fixtures are recorded.

### Phase 3 — LLM agent
Provider interface with Ollama by default; model chosen by measurement; the bounded tool loop; untrusted-content handling; strict output parsing; degradation to the baseline; recording and replay; injection fixtures and the influence metric.
**Exit:** a full agent-vs-baseline eval (N runs per fixture) with accuracy, spread, outcome matrix, rejection rates, injection influence, latency and tokens recorded, whichever ranker wins; CI green in replay mode.

### Phase 4 — Product, operations, measurements, docs
React UI (timeline, per-claim status, evidence viewer, comparison, verdicts, follow-ups, audit view) with the XSS test; live end-to-end runs on injected failures; resumable investigations; chaos runs (LLM down mid-investigation, telemetry spike during an investigation); observability; fixture set grown to ≥ 30; static public demo on GitHub Pages; postmortems; `docs/how-sentry-rca-was-built.md` and `docs/interview-guide.md`.
**Exit:** every §1.2 and §1.4 number recorded with its command; all guard checks pass; the public demo works; both documents finished; CI green.

---

## 17. Load and chaos testing

| Test | Setup | Recorded |
|---|---|---|
| Ingestion ceiling | Ramp synthetic OTLP from 1k to the point lag grows unbounded | Ceiling and bottleneck |
| ClickHouse query latency | Increase label cardinality | Where tool-query latency degrades |
| Alert latency | Inject each scenario | Anomaly onset → incident |
| Investigation latency | Single-service and multi-hop fixtures | First verified hypothesis and final outcome, separately |
| Concurrency | Several incidents at once | Max concurrent investigations before latency degrades |
| Accuracy | Full eval, both rankers | §1.4 metrics |
| Adversarial | Verifier suite, injection fixtures, scope escapes, XSS payload | All defences hold; influence rate |
| Chaos: LLM down | Stop Ollama mid-investigation | `degraded_baseline`; no lost data |
| Chaos: spike during investigation | 10× telemetry during a run | Investigation unaffected or degraded gracefully |
| Memory | Full stack with the model | RSS per container and total |

---

## 18. Architecture decision records

| ADR | Decision |
|---|---|
| 000 | LLM provider behind a swappable interface; Ollama by default; record and replay for CI; temperature 0 |
| 001 | ClickHouse for metrics, logs and traces in one columnar store, instead of a TSDB plus a search engine; when it would flip (trace volume or full-text needs diverging) |
| 002 | pgvector instead of a dedicated vector database; when it would flip (corpus in the hundreds of thousands of chunks, or hybrid retrieval with reranking) |
| 003 | Redpanda (Kafka API) for ingestion instead of Pub/Sub or direct writes; contrast with Concord |
| 004 | Rule-based and statistical alerting instead of ML anomaly detection, for determinism and explainability |
| 005 | Read-only tools as a hard boundary; what a write-capable version would require |
| 006 | Causal-ranking heuristic instead of formal causal inference; its known blind spot (no trace path) |
| 007 | Typed claims and a deterministic verifier, instead of citation-existence checks or an LLM judge |
| 008 | Scope from a server-side dependency-graph allowlist, instead of overwriting the service argument |
| 009 | No Redis: what moved to Postgres and process memory, and why it is enough at this scale |
| 010 | Hand-written tool loop instead of an agent framework |
| 011 | Laptop-only platform and a static public demo instead of cloud hosting |
| 012 | Content-addressed evidence snapshots instead of live re-queries |

---

## 19. Open decisions

1. **Model**: which local model (for example a 7–8B instruct model versus a 3–4B one) after measuring accuracy, latency and memory on the laptop; and whether to run an optional free-tier hosted model for a comparison eval.
2. **Embedding model** for runbooks (sets the `vector(768)` dimension).
3. **Thresholds**: defaults for `min_magnitude` guidance, baseline window length, `max_deploy_gap`, `runbook_min_similarity`, `conflict_margin`; confirm after the first baseline eval.
4. **Scope**: `scope_depth` (default 2) and window margins (30 min before, 15 min after).
5. **Budget**: 20 tool calls, 60,000 tokens and 120 s per investigation, to be confirmed against the chosen model's speed.
6. **Eval**: N = 5 runs per fixture, and the gate tolerances in §12.5.
7. **ClickHouse dedup reads**: `FINAL` versus `argMax` per tool, decided by measured query cost.
8. **UI auth**: single local user versus per-tenant users for the demo.
9. **Fixture target**: 30 minimum; whether to aim higher before Phase 4 docs.
10. **Demo service language**: Python for all four, or one in another language to show trace propagation across runtimes.

---

## Amendments

Decisions taken while building, each landed in the same commit as the code it governs.

| # | Phase | Section | Amendment | Why |
|---|---|---|---|---|
| A1 | 1 | §2.1, §4.2, §16 | Alerting is symptom-based at the edge: the seeded rule set is one composite SLO rule on `gateway` (`any_of` error-rate threshold, p95 latency z-score). Every scenario therefore opens its one incident on `gateway`; finding the cause is the investigation's job. Rules on other services remain possible but are not seeded. | §16 requires exactly one incident per scenario, but a multi-hop failure trips per-service rules on 3–4 services, each with a distinct fingerprint (service + condition + rule id), and the spec has no cross-service grouping. Scope depth 2 from `gateway` reaches every service. |
| A2 | 1 | §3 | payments calls `inventory /holds/confirm` before charging and retries failed calls (3 retries, exponential backoff, CPU-costing request signing per attempt). The `pool_exhaustion` scenario exhausts **inventory's** pool. | §3 says pool exhaustion causes a "payments retry storm", but the §3 topology gave payments no call path to the pool's service. |
| A3 | 1 | §3 | `noisy_neighbor`'s job is a `batchjob` container pinned to the same core (`cpuset`) as payments and inventory; it emits only its own CPU/memory metrics. Label: `root_cause = {service: "batchjob", cause_kind: "noisy_neighbor"}`, `expected_outcome = "INSUFFICIENT_EVIDENCE"`. | §3 named "the job" with no expected outcome. A job with no trace edges is never inside the §5.2 allowlist, so no ranker can cite it; the only outcome that does not manufacture a conclusion is `INSUFFICIENT_EVIDENCE`, and blaming a victim service scores as wrong. |
| A4 | 1 | §12.1 | §12.1's per-category minimums (3 multi-hop, 3 ambiguous, 3 no-signal, 3 noisy-neighbour, 5 injection) apply to the ≥ 30 fixtures at the end of Phase 4. Phase 1's minimums are ≥ 15 fixtures with ≥ 3 multi-hop, 3 ambiguous, 3 no-signal, 2 noisy-neighbour and 2 injection. | §12.1 put both fixture totals and one set of category minimums in one sentence; the Phase 1 brief set 2 noisy-neighbour and 2 injection. |
| A5 | 1 | §4.1, §4.4 | The archive job exports each complete UTC day of logs and spans when it is 6 days old (before the 7-day TTL can delete any of it), catches up day 7 if a run was missed (marked possibly partial), archives each day once, and deletes archives older than 90 days. | "Archive logs and spans older than 7 days" contradicted the 7-day TTL on those tables: by then the rows may already be gone. |
| A6 | 1 | §3, §8.1 | Fixture gold claims use the §8.1 claim shape, but each cite is `{"tool": <§5.1 tool>, "args": {...}, "row_ids": [stable telemetry IDs]}` instead of `tool_call_seq`; Phase 2's eval harness executes each cite as a tool call and rewrites it to `tool_call_seq` before verification. Phase 1 gold claims are `metric_change`, `log_pattern` and `trace_dependency`; `deploy_precedes_onset` gold claims (which cite timeline rows) are added in Phase 2 as new dataset versions. | No investigation, and so no tool call, exists when a fixture is recorded. |
| A7 | 1 | §5.2, §19.4 | Fixtures record the window `first_anomaly_at − 15 min` to `last_seen + 5 min`; in fixture evals the §5.2 scope window is clamped to the recorded window. Live scope defaults (30 min before / 15 after) are unchanged. | Fixtures must not overlap another fault's window; 15/5 margins make a 19-fixture campaign ~7 h instead of ~14 h, and 15 min still covers §8.2's 15-minute `metric_change` baseline. |
| A8 | 1 | §19 (thresholds) | Alert defaults: evaluate every 5 s over a trailing 60 s window, 2 consecutive breaches. Error rate = 5xx / requests > 5 % with ≥ 20 requests. Latency: p95 robust z-score (median/MAD of 1-minute p95s over the trailing 30 min, ≥ 10 baseline minutes) > 4, and p95 > 1.5 × baseline median, and p95 − median > 20 ms. Auto-resolve after 3 min without a breach (the C11 operational meaning of `status`; the spec gave no resolve rule). | The ratio and absolute floors stop background wobble firing; median/MAD keeps a previous incident in the trailing window from masking the next; 2 × 5 s keeps detection well inside the 30 s target. |
