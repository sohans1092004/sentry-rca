# ADR-008: Scope from a server-side dependency-graph allowlist

**Status:** Accepted (Phase 2).

## Context

Rankers (the baseline now, an LLM agent in Phase 3) choose their own tool arguments. Arguments are
requests, not authority: a model can be talked into asking for another tenant, every service, or a
month of data. v1 overwrote every call's `service` with the incident's service, which made
cross-service causal chains (an inventory pool behind a gateway incident) impossible to investigate.

## Decision

Per investigation, the server computes a scope once and stores it (`investigation/scope.py`, §5.2):

- **tenant** from the incident row; no argument can change it (a `tenant`/`tenant_id` argument that
  differs is rejected; every query filters by the scope's tenant regardless);
- **services**: the incident's service plus everything within 2 hops in the undirected graph of
  `service_edges` over the last 24 h plus the incident window;
- **window**: `first_anomaly_at − 30 min .. last_seen + 15 min`, clamped to a fixture's recorded
  window in evals (A7);
- **caps**: 500 rows, 256 KB per result; `limit`/`top_k` clamped.

`investigation/tools.py` `prepare()` applies it before anything runs: out of scope → `rejected`, with
the reason, an audit row and an error result; out of bounds → `clamped`, executed within bounds, the
clamp recorded. The executed request, not the requested one, is what runs and what the audit stores.

## Consequences

- A scope escape is impossible by construction, not by prompt: no code path runs a request that
  `prepare()` did not produce. Tested per tool, guard-checked for the tenant filter, the allowlist and
  the caps.
- **Depth 2 from the edge reaches every demo service** (gateway → orders → inventory/payments), so
  edge SLO alerting (A1) does not hide causes. It does not reach `provider` (3 hops) or anything with
  no trace edge at all, such as the `noisy_neighbor` batch job (ADR-006).
- The graph is only as good as the instrumentation that names callees (`peer.service` or
  `server.address` on CLIENT spans, ADR-001).
- Scope is stored once: a resumed investigation keeps its original scope even if the graph grew.
