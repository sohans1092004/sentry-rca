-- SPEC §4.2, Phase 2 subset, with Amendments A15 (ranker per hypothesis/tool call, per-ranker
-- results). llm_exchanges and verdicts arrive in Phases 3-4.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE investigations (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  incident_id UUID NOT NULL REFERENCES incidents(id),
  trigger_id TEXT NOT NULL,                  -- event id of the trigger, for idempotency
  trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('auto','reinvestigate','follow_up')),
  follow_up_question TEXT,
  ranker TEXT NOT NULL CHECK (ranker IN ('agent','baseline')),   -- the result shown to the human (A15)
  status TEXT NOT NULL CHECK (status IN ('running','complete','failed','degraded_baseline')),
  outcome TEXT CHECK (outcome IN ('ROOT_CAUSE_IDENTIFIED','INSUFFICIENT_EVIDENCE','CONFLICTING_EVIDENCE')),
  scope JSONB NOT NULL,                      -- tenant, allowed services, window, caps
  budget_used JSONB NOT NULL DEFAULT '{}',   -- tool calls, tokens, wall ms
  human_marked_unresolved BOOLEAN NOT NULL DEFAULT false,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  UNIQUE (incident_id, trigger_id)
);

-- each ranker's own outcome (A15); investigations.outcome is the one shown
CREATE TABLE investigation_results (
  investigation_id UUID NOT NULL REFERENCES investigations(id),
  ranker TEXT NOT NULL CHECK (ranker IN ('agent','baseline')),
  outcome TEXT NOT NULL CHECK (outcome IN ('ROOT_CAUSE_IDENTIFIED','INSUFFICIENT_EVIDENCE','CONFLICTING_EVIDENCE')),
  completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (investigation_id, ranker)
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
  ranker TEXT NOT NULL CHECK (ranker IN ('agent','baseline')),   -- A15
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
  ranker TEXT NOT NULL CHECK (ranker IN ('agent','baseline')),   -- A15
  rank INT NOT NULL,
  causal_role TEXT NOT NULL CHECK (causal_role IN ('candidate_root_cause','downstream_symptom')),
  cause_service TEXT NOT NULL,
  cause_kind TEXT NOT NULL,
  score DOUBLE PRECISION NOT NULL,           -- ranker's score, for the tie rule (§7.5)
  narrative TEXT,                            -- shown as "unverified explanation"
  verifier_status TEXT NOT NULL CHECK (verifier_status IN ('passed','rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (investigation_id, ranker, rank)
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

CREATE TABLE runbooks (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL,
  title TEXT NOT NULL, body TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('runbook','postmortem')),
  fixture_id TEXT,                           -- set for postmortems written about a fixture
  embedding vector(768) NOT NULL
);
CREATE INDEX runbooks_hnsw ON runbooks USING hnsw (embedding vector_cosine_ops);

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
