-- Demo tenant and the single edge SLO rule (Amendments A1, A8).
-- api_key_hash '!' matches no key: API auth arrives in Phase 4.
INSERT INTO tenants (id, name, api_key_hash)
VALUES ('00000000-0000-4000-8000-000000000001', 'demo', '!')
ON CONFLICT DO NOTHING;

INSERT INTO alert_rules (id, tenant_id, service, metric, condition)
VALUES ('00000000-0000-4000-8000-0000000000a1', '00000000-0000-4000-8000-000000000001',
        'gateway', 'http.server.request.duration',
        '{"name": "slo", "window_s": 60, "consecutive": 2,
          "any_of": [
            {"kind": "error_rate", "threshold": 0.05, "min_requests": 20},
            {"kind": "latency_zscore", "quantile": 0.95, "baseline_s": 1800, "z": 4.0,
             "min_ratio": 1.5, "min_delta_ms": 20, "min_baseline_points": 10}
          ]}')
ON CONFLICT DO NOTHING;
