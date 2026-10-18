-- SPEC §4.2, Phase 1 subset.
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

CREATE TABLE fixtures (
  id TEXT PRIMARY KEY, scenario TEXT NOT NULL, dataset_path TEXT NOT NULL,
  label JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
