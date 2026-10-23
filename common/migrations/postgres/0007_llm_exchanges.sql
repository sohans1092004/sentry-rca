-- SPEC §4.2 / §7.4 (Phase 3): every model call, for audit and replay. Append-only for the app role,
-- like the other audit tables. request_hash is the replay key (A35): sha256 of model, model digest,
-- the canonical request (data-block boundaries replaced by a placeholder) and the run index.
CREATE TABLE llm_exchanges (
  id UUID PRIMARY KEY,
  investigation_id UUID NOT NULL REFERENCES investigations(id),
  seq INT NOT NULL,
  provider TEXT NOT NULL, model TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  request JSONB NOT NULL, response JSONB NOT NULL,
  tokens_in INT, tokens_out INT, latency_ms INT,
  UNIQUE (investigation_id, seq)
);

REVOKE ALL ON llm_exchanges FROM sentry_app;
GRANT SELECT, INSERT ON llm_exchanges TO sentry_app;
