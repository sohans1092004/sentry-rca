# ADR-009: No Redis

**Status:** Accepted (Phase 2).

## Context

v1 used Redis for an investigation concurrency limiter, an alert dedup window and query caches. Each
is real state with failure modes, and Redis is one more stateful container on a laptop budget.

## Decision

No Redis. What it held moved to stores that already exist:

| Need | Where it lives now |
|---|---|
| Alert grouping / dedup window | the `incidents_one_open` partial unique index + `last_seen` (Phase 1) |
| `incidents.opened` exactly-once effect | `UNIQUE (incident_id, trigger_id)` on `investigations` |
| Concurrency cap (`max_concurrent_investigations = 2`) | Postgres session advisory locks, one per slot (`orchestrator.acquire_slot`) |
| Within-investigation query cache | an in-memory map in `ToolLayer`, keyed by the canonical executed request, discarded with the investigation |
| Resume after a crash | the persisted `tool_calls` rows themselves (`ToolLayer` replays them) |

## Consequences

- One fewer container and no cache coherence problem: the only cache dies with the investigation,
  so it can never serve another tenant or a stale result across investigations.
- Advisory locks are released when the holding session ends, so a crashed orchestrator frees its slot.
- The ceiling is Postgres: at hundreds of concurrent investigations the advisory-lock polling and the
  per-call audit inserts would be the first load. Not a concern at 2.
