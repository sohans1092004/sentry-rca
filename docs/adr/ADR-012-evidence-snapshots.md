# ADR-012: Content-addressed evidence snapshots, not live re-queries

**Status:** Accepted (Phase 2).

## Context

A claim cites rows. Hot telemetry lives 7 days (§4.4); a citation that points at live ClickHouse rows
breaks when they expire, and silently changes meaning if they are rewritten. The verifier, the UI and
the static demo all need the exact rows the ranker saw.

## Decision

Every tool result is stored in `evidence_snapshots` **before** it is returned to the ranker
(`investigation/tools.py` `ToolLayer.call`, `investigation/snapshots.py`):

- content = canonical JSON of `{tenant_id, rows, truncated}` (sorted keys, no whitespace, UTC
  millisecond timestamps), zstd-compressed;
- id = SHA-256 of that content, so identical results of one tenant share one row (the tenant is in
  the hash, so two tenants never share one);
- over 500 rows or 256 KB the result is cut and marked `truncated`; claims can cite only rows present;
- the rows returned to the ranker are the JSON round-trip of what was stored, so ranker, verifier and
  UI see byte-identical data;
- the snapshot and the `tool_calls` audit row are written in one transaction, then the result returns.

The verifier resolves citations only from snapshots.

## Consequences

- Citations survive retention and deletion of the underlying telemetry (tested by deleting the
  ClickHouse rows, then verifying; guard check `snapshot_before_return`).
- Storage grows with every distinct result (bounded at 256 KB each, compressed); content addressing
  makes repeated identical queries free.
- `evidence_snapshots` and `tool_calls` are append-only for the application role (INSERT and SELECT
  only; guard check `append_only_grants`).
