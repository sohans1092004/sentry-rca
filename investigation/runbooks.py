"""Runbook corpus and search_runbooks (SPEC §5.1, §12.2).

Documents are markdown files under runbooks/ with a small header (`title:`, `kind:`, optional
`fixture_id:`). Postmortems written about a fixture carry its fixture_id and are never returned while
that fixture is evaluated (the contamination rule); every other document is searchable.
"""

import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from investigation.embeddings import Cassette

CORPUS = Path(__file__).resolve().parent.parent / "runbooks"
_NS = uuid.UUID("1c4f7f0e-2b8d-4d0a-9a7c-6a3a5e1d2f90")
EXCERPT = 300


@dataclass(frozen=True)
class Doc:
    id: str
    title: str
    kind: str
    fixture_id: str | None
    body: str

    @property
    def text(self) -> str:  # what is embedded; nomic-embed-text expects a task prefix
        return f"search_document: {self.title}\n{self.body}"


def read_corpus(root: Path = CORPUS) -> list[Doc]:
    docs = []
    for f in sorted(root.rglob("*.md")):
        head, _, body = f.read_text(encoding="utf-8").partition("\n---\n")
        meta = dict(line.split(": ", 1) for line in head.strip().splitlines())
        docs.append(Doc(str(uuid.uuid5(_NS, f.relative_to(root).as_posix())), meta["title"], meta["kind"],
                        meta.get("fixture_id"), body.strip()))  # fmt: skip
    return docs


def query_text(q: str) -> str:
    return f"search_query: {q}"


def load(conn: psycopg.Connection[Any], cassette: Cassette, tenant: str, docs: list[Doc]) -> int:
    with conn.transaction():
        conn.execute("DELETE FROM runbooks WHERE tenant_id = %s", (tenant,))
        for d in docs:
            conn.execute(
                "INSERT INTO runbooks (id, tenant_id, title, body, kind, fixture_id, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::vector)",
                (d.id, tenant, d.title, d.body, d.kind, d.fixture_id, str(cassette.embed(d.text))),
            )
    return len(docs)


class PgRunbookIndex:
    def __init__(self, conn: psycopg.Connection[Any], cassette: Cassette):
        self.conn, self.cassette = conn, cassette

    def search(self, tenant: str, query: str, top_k: int, exclude_fixture: str | None) -> list[dict[str, Any]]:
        q = str(self.cassette.embed(query_text(query)))
        rows = self.conn.execute(
            "SELECT id::text, title, kind, fixture_id, left(body, %s), 1 - (embedding <=> %s::vector) AS similarity "
            "FROM runbooks WHERE tenant_id = %s "
            "AND (fixture_id IS NULL OR fixture_id <> COALESCE(%s, '')) "  # SPEC §12.2 contamination rule
            "ORDER BY embedding <=> %s::vector, id LIMIT %s",
            (EXCERPT, q, tenant, exclude_fixture, q, top_k),
        ).fetchall()
        return [{"row_id": i, "doc_id": i, "title": t, "kind": k, "fixture_id": f, "excerpt": b, "similarity": s}
                for i, t, k, f, b, s in rows]  # fmt: skip


class MemoryRunbookIndex:
    """Same ranking in Python, for unit tests: cosine similarity over the cassette's float32 vectors."""

    def __init__(self, docs: list[Doc], cassette: Cassette):
        self.docs = docs
        self.cassette = cassette
        self.vecs = {d.id: cassette.embed(d.text) for d in docs}

    def search(self, tenant: str, query: str, top_k: int, exclude_fixture: str | None) -> list[dict[str, Any]]:
        q = self.cassette.embed(query_text(query))
        scored = []
        for d in self.docs:
            if d.fixture_id is not None and d.fixture_id == (exclude_fixture or ""):
                continue  # SPEC §12.2 contamination rule
            v = self.vecs[d.id]
            sim = sum(a * b for a, b in zip(q, v, strict=True)) / (math.hypot(*q) * math.hypot(*v))
            scored.append((-sim, d.id, d, sim))
        scored.sort(key=lambda x: (x[0], x[1]))
        return [{"row_id": d.id, "doc_id": d.id, "title": d.title, "kind": d.kind, "fixture_id": d.fixture_id,
                 "excerpt": d.body[:EXCERPT], "similarity": sim} for _, _, d, sim in scored[:top_k]]  # fmt: skip
