"""Evidence snapshots (SPEC §4.3): every tool result is stored before it is returned.

Content is canonical JSON of {tenant_id, rows, truncated}; the id is its SHA-256, so identical
results of one tenant share a row (the tenant is part of the hash, so two tenants never do). Results
over MAX_ROWS rows or MAX_BYTES bytes are cut, oldest-first order kept, and marked truncated.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
import zstandard

MAX_ROWS = 500
MAX_BYTES = 262_144


def _default(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    raise TypeError(f"not JSON-serialisable: {type(v).__name__}")


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default).encode()


@dataclass(frozen=True)
class Snapshot:
    id: str
    tenant_id: str
    rows: list[dict[str, Any]]
    truncated: bool
    content: bytes  # canonical JSON

    @property
    def byte_size(self) -> int:
        return len(self.content)


def build(tenant_id: str, rows: list[dict[str, Any]], truncated: bool = False) -> Snapshot:
    """Cap rows and bytes, then hash. Every row must already carry its row_id. `truncated` marks a
    result the tool already cut at its limit."""
    assert all("row_id" in r for r in rows), "every row carries a row_id (SPEC §4.3)"
    truncated = truncated or len(rows) > MAX_ROWS
    kept = rows[:MAX_ROWS]
    content = canonical({"tenant_id": tenant_id, "rows": kept, "truncated": truncated})
    while len(content) > MAX_BYTES:
        # drop from the end until it fits; claims can only cite rows that are present
        kept = kept[: max(0, int(len(kept) * MAX_BYTES / len(content)) - 1)]
        truncated = True
        content = canonical({"tenant_id": tenant_id, "rows": kept, "truncated": truncated})
    return Snapshot(hashlib.sha256(content).hexdigest(), tenant_id, kept, truncated, content)


def store(conn: psycopg.Connection[Any], snap: Snapshot) -> None:
    conn.execute(
        "INSERT INTO evidence_snapshots (id, tenant_id, content, byte_size, row_count) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO NOTHING",
        (
            snap.id,
            snap.tenant_id,
            zstandard.ZstdCompressor(level=3).compress(snap.content),
            snap.byte_size,
            len(snap.rows),
        ),
    )


def load(conn: psycopg.Connection[Any], snapshot_id: str) -> Snapshot:
    row = conn.execute(
        "SELECT tenant_id::text, content FROM evidence_snapshots WHERE id = %s", (snapshot_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no snapshot {snapshot_id}")
    content = zstandard.ZstdDecompressor().decompress(bytes(row[1]))
    body = json.loads(content)
    return Snapshot(snapshot_id, str(row[0]), body["rows"], bool(body["truncated"]), content)
