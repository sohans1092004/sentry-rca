-- The application's role (SPEC §4.2 Append-only audit): INSERT and SELECT only on the audit tables,
-- UPDATE and DELETE revoked. Roles are cluster-wide, grants are per database.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sentry_app') THEN
    CREATE ROLE sentry_app LOGIN PASSWORD 'sentry_app';
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO sentry_app;
GRANT SELECT ON tenants, alert_rules, fixtures, runbooks TO sentry_app;
GRANT SELECT, INSERT, UPDATE ON incidents, investigations, investigation_results, eval_runs, eval_results
  TO sentry_app;
REVOKE ALL ON tool_calls, evidence_snapshots, hypotheses, claims, claim_citations FROM sentry_app;
GRANT SELECT, INSERT ON tool_calls, evidence_snapshots, hypotheses, claims, claim_citations TO sentry_app;
