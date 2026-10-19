"""Fixture datasets: export a telemetry window to Parquet, hash it, and load it into an isolated
ClickHouse database (SPEC §3, §4.1 Evals, §12.1). Parquet stays local (data/fixtures/); the
label, injection record and manifest are committed under fixtures/."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from clickhouse_connect.driver.client import Client

TS = pa.timestamp("ms", tz="UTC")
STRMAP = pa.map_(pa.string(), pa.string())
TABLES: dict[str, dict[str, Any]] = {
    "metrics": {
        "schema": pa.schema([("tenant_id", pa.string()), ("service", pa.string()), ("metric", pa.string()),
                             ("labels", STRMAP), ("ts", TS), ("value", pa.float64()), ("point_id", pa.string())]),
        "key": "point_id", "time": "ts",
    },
    "logs": {
        "schema": pa.schema([("tenant_id", pa.string()), ("service", pa.string()), ("ts", TS),
                             ("severity", pa.string()), ("body", pa.string()), ("trace_id", pa.string()),
                             ("span_id", pa.string()), ("attrs", STRMAP), ("log_id", pa.string())]),
        "key": "log_id", "time": "ts",
    },
    "spans": {
        "schema": pa.schema([("tenant_id", pa.string()), ("trace_id", pa.string()), ("span_id", pa.string()),
                             ("parent_span_id", pa.string()), ("service", pa.string()), ("name", pa.string()),
                             ("start_ts", TS), ("duration_ms", pa.float64()), ("status", pa.string()),
                             ("attrs", STRMAP)]),
        "key": "trace_id, span_id", "time": "start_ts",
    },
    # deploys live in ClickHouse too (Amendment A9), so an eval reads one self-contained database
    "deploys": {
        "schema": pa.schema([("id", pa.string()), ("tenant_id", pa.string()), ("service", pa.string()),
                             ("version", pa.string()), ("started_at", TS), ("finished_at", TS)]),
        "key": "id", "time": "finished_at",
    },
}  # fmt: skip


def _norm(v: Any) -> Any:
    """One canonical form for a value read from ClickHouse, Postgres or Parquet."""
    if isinstance(v, datetime):
        return int(v.astimezone(UTC).timestamp() * 1000) if v.tzinfo else int(v.replace(tzinfo=UTC).timestamp() * 1000)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return sorted((str(k), str(x)) for k, x in v.items())
    if isinstance(v, list):  # pyarrow maps come back as [(k, v), ...]
        return sorted((str(k), str(x)) for k, x in v)
    return v


def content_hash(rows: list[dict[str, Any]], columns: list[str]) -> str:
    """Order-independent: sha256 over the sorted canonical JSON of every row."""
    lines = sorted(json.dumps([_norm(r[c]) for c in columns], separators=(",", ":")) for r in rows)
    h = hashlib.sha256()
    for line in lines:
        h.update(line.encode())
        h.update(b"\n")
    return h.hexdigest()


def _rows(result: Any) -> list[dict[str, Any]]:
    """Rows as dicts; ClickHouse DateTime64 columns come back naive and are UTC."""
    cols = list(result.column_names)
    out = [dict(zip(cols, r, strict=True)) for r in result.result_rows]
    for r in out:
        for k, v in r.items():
            if isinstance(v, datetime) and v.tzinfo is None:
                r[k] = v.replace(tzinfo=UTC)
    return out


def read_ch(ch: Client, table: str, tenant: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    spec = TABLES[table]
    cols = ", ".join(spec["schema"].names)
    # Dedup with LIMIT 1 BY the stable key, not FINAL: spans are ordered by trace_id, so a time filter
    # cannot prune them and FINAL merges every part of the table while reading. It ran ClickHouse out
    # of memory (code 241) on a 38M-row spans table. Redelivered copies are identical, so keeping
    # any one of them is what FINAL would return.
    return _rows(ch.query(
        f"SELECT {cols} FROM {table} WHERE tenant_id = {{t:String}} "
        f"AND {spec['time']} >= {{s:DateTime64(3)}} AND {spec['time']} <= {{e:DateTime64(3)}} "
        f"ORDER BY {spec['key']} LIMIT 1 BY {spec['key']}",
        parameters={"t": tenant, "s": start, "e": end},
    ))  # fmt: skip


def arrow_table(table: str, rows: list[dict[str, Any]]) -> pa.Table:
    schema = TABLES[table]["schema"]
    return pa.table({c: [_arrow(r[c]) for r in rows] for c in schema.names}, schema=schema)


def write_parquet(path: Path, table: str, rows: list[dict[str, Any]]) -> None:
    pq.write_table(arrow_table(table, rows), path, compression="zstd")


def _arrow(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return list(v.items())
    return v


def read_parquet(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = pq.read_table(path).to_pylist()
    for r in rows:
        for k, v in r.items():
            if isinstance(v, list):
                r[k] = dict(v)
    return rows


def export(out: Path, tables: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Write each table to Parquet; return the manifest (row counts and content hashes)."""
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"tables": {}}
    for name, rows in tables.items():
        write_parquet(out / f"{name}.parquet", name, rows)
        manifest["tables"][name] = {"rows": len(rows), "sha256": content_hash(rows, TABLES[name]["schema"].names)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


class DatasetMismatch(Exception):
    pass


def verify_hashes(dataset: Path, ch: Client, database: str) -> None:
    """The loaded database must hold exactly what the manifest says, row for row."""
    manifest = json.loads((dataset / "manifest.json").read_text())
    for name, expected in manifest["tables"].items():
        cols = TABLES[name]["schema"].names
        rows = _rows(ch.query(f"SELECT {', '.join(cols)} FROM `{database}`.{name} FINAL"))
        got = {"rows": len(rows), "sha256": content_hash(rows, cols)}
        if got != expected:
            raise DatasetMismatch(f"{dataset.name}/{name}: manifest {expected}, loaded {got}")
