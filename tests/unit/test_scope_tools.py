"""Scope (§5.2), the tool layer (§5.1, §4.3) and the outcome rules (§7.5), over synthetic offline data."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from investigation import outcome, snapshots
from investigation.backend import OfflineBackend
from investigation.embeddings import Cassette, _pack
from investigation.runbooks import Doc, MemoryRunbookIndex, query_text
from investigation.scope import Scope, allowed_services, compute, iso
from investigation.tools import MemoryStore, ToolLayer, execute

A, B = "tenant-a", "tenant-b"
T0 = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
EDGES = [
    ("gateway", "orders", 9),
    ("orders", "inventory", 9),
    ("orders", "payments", 9),
    ("payments", "inventory", 9),
    ("payments", "provider", 9),
]


def span(tenant, tid, sid, parent, svc, kind="SERVER", peer=None, ms=10.0, t=T0):
    attrs = {"span.kind": kind, **({"peer.service": peer} if peer else {})}
    return {
        "tenant_id": tenant,
        "trace_id": tid,
        "span_id": sid,
        "parent_span_id": parent,
        "service": svc,
        "name": "op",
        "start_ts": t,
        "duration_ms": ms,
        "status": "UNSET",
        "attrs": attrs,
    }


def tables(n_metrics=10):
    m = [
        {
            "tenant_id": tn,
            "service": svc,
            "metric": "lat",
            "labels": {"route": "/x"},
            "ts": T0 + timedelta(seconds=5 * i),
            "value": float(i),
            "point_id": f"{tn}-{svc}-{i}",
        }
        for tn in (A, B)
        for svc in ("orders", "batchjob")
        for i in range(n_metrics)
    ]
    s = [
        span(A, "t1", "g", "", "gateway"),
        span(A, "t1", "gc", "g", "gateway", "CLIENT", "orders"),
        span(A, "t1", "o", "gc", "orders"),
        span(A, "t1", "oc", "o", "orders", "CLIENT", "inventory"),
        span(A, "t1", "i", "oc", "inventory"),
        span(A, "t1", "oc2", "o", "orders", "CLIENT", "payments"),
        span(A, "t1", "p", "oc2", "payments"),
        span(A, "t1", "pc", "p", "payments", "CLIENT", "provider"),
        span(A, "t1", "x", "p", "batchjob"),  # a span from an out-of-scope service in the same trace
        span(B, "t9", "b", "", "orders"),
    ]
    lg = [
        {
            "tenant_id": tn,
            "service": "orders",
            "ts": T0 + timedelta(seconds=i),
            "severity": "ERROR",
            "body": f"boom\x07 {'y' * 600}",
            "trace_id": "",
            "span_id": "",
            "attrs": {},
            "log_id": f"{tn}-l{i}",
        }
        for tn in (A, B)
        for i in range(3)
    ]
    return {"metrics": m, "spans": s, "logs": lg, "deploys": []}


def scope(services=("gateway", "inventory", "orders", "payments")):
    return Scope(A, "gateway", tuple(services), T0 - timedelta(minutes=30), T0 + timedelta(minutes=30))


W = {"start": iso(T0 - timedelta(minutes=5)), "end": iso(T0 + timedelta(minutes=5))}


# --- scope ---------------------------------------------------------------------------------------


def test_allowlist_is_depth_2_bfs_over_undirected_edges():
    assert allowed_services(EDGES, "gateway", 2) == ("gateway", "inventory", "orders", "payments")
    assert allowed_services(EDGES, "gateway", 3) == ("gateway", "inventory", "orders", "payments", "provider")
    assert allowed_services(EDGES, "inventory", 1) == ("inventory", "orders", "payments")  # undirected


def test_scope_window_and_edges_from_the_data():
    be = OfflineBackend(tables())
    inc = {"tenant_id": A, "service": "gateway", "first_anomaly_at": T0, "last_seen": T0 + timedelta(minutes=5)}
    sc = compute(be, inc)
    assert sc.services == ("gateway", "inventory", "orders", "payments")  # batchjob has no edge; provider is 3 hops
    assert (sc.start, sc.end) == (T0 - timedelta(minutes=30), T0 + timedelta(minutes=20))
    clamped = compute(be, inc, clamp=(T0 - timedelta(minutes=15), T0 + timedelta(minutes=10)))
    assert (clamped.start, clamped.end) == (T0 - timedelta(minutes=15), T0 + timedelta(minutes=10))
    assert Scope.from_json(json.loads(json.dumps(sc.to_json()))) == sc


# --- tenant, allowlist, window, caps -------------------------------------------------------------


def test_tenant_is_forced():
    be = OfflineBackend(tables())
    d = execute(be, None, scope(), "query_metrics", {"service": "orders", "metric": "lat", **W})
    assert d.decision == "allowed" and d.rows and all(r["row_id"].startswith(A) for r in d.rows)
    d = execute(be, None, scope(), "query_logs", {"service": "orders", **W})
    assert d.rows and all(r["row_id"].startswith(A) for r in d.rows)
    d = execute(be, None, scope(), "query_metrics", {"service": "orders", "metric": "lat", "tenant_id": B, **W})
    assert d.decision == "rejected" and "not this investigation's tenant" in d.reason


def test_service_outside_the_allowlist_is_rejected_with_a_reason():
    be = OfflineBackend(tables())
    for tool, args in (
        ("query_metrics", {"service": "batchjob", "metric": "lat"}),
        ("query_logs", {"service": "batchjob"}),
        ("get_recent_deploys", {"service": "batchjob"}),
        ("query_traces", {"service": "batchjob"}),
        ("get_incident_timeline", {"services": ["orders", "batchjob"]}),
    ):
        d = execute(be, None, scope(), tool, {**args, **W})
        assert d.decision == "rejected" and "batchjob outside scope" in d.reason and d.rows == [], tool


def test_trace_rows_are_limited_to_the_allowlist():
    d = execute(OfflineBackend(tables()), None, scope(), "query_traces", {"trace_id": "t1", **W})
    services = {r["service"] for r in d.rows}
    assert services == {"gateway", "orders", "inventory", "payments"}  # the batchjob span is not returned


def test_window_is_clamped_and_recorded():
    sc = scope()
    d = execute(
        OfflineBackend(tables()),
        None,
        sc,
        "query_metrics",
        {
            "service": "orders",
            "metric": "lat",
            "start": iso(T0 - timedelta(days=2)),
            "end": iso(T0 + timedelta(days=2)),
        },
    )
    assert d.decision == "clamped" and d.executed["start"] == iso(sc.start) and d.executed["end"] == iso(sc.end)
    d = execute(
        OfflineBackend(tables()),
        None,
        sc,
        "query_metrics",
        {
            "service": "orders",
            "metric": "lat",
            "start": iso(T0 + timedelta(days=2)),
            "end": iso(T0 + timedelta(days=3)),
        },
    )
    assert d.decision == "rejected" and "entirely outside scope" in d.reason


def test_limit_and_rows_and_bytes_are_capped():
    be = OfflineBackend(tables(n_metrics=700))
    d = execute(be, None, scope(), "query_logs", {"service": "orders", "limit": 10_000, **W})
    assert d.decision == "clamped" and d.executed["limit"] == 500
    wide = Scope(A, "gateway", ("orders",), T0 - timedelta(hours=1), T0 + timedelta(hours=3))
    d = execute(
        be,
        None,
        wide,
        "query_metrics",
        {"service": "orders", "metric": "lat", "start": iso(T0), "end": iso(T0 + timedelta(hours=2))},
    )
    assert len(d.rows) == 500 and d.truncated
    snap = snapshots.build(A, [{"row_id": str(i), "blob": "z" * 1000} for i in range(400)])
    assert snap.byte_size <= snapshots.MAX_BYTES and snap.truncated and len(snap.rows) < 400


def test_log_bodies_are_truncated_and_stripped_of_control_characters():
    d = execute(OfflineBackend(tables()), None, scope(), "query_logs", {"service": "orders", **W})
    assert all(len(r["body"]) == 500 and "\x07" not in r["body"] for r in d.rows)


def test_unknown_tools_and_arguments_are_rejected():
    be = OfflineBackend(tables())
    assert execute(be, None, scope(), "drop_table", {}).decision == "rejected"
    d = execute(be, None, scope(), "query_logs", {"service": "orders", "sql": "DROP", **W})
    assert d.decision == "rejected" and "unknown argument" in d.reason


# --- snapshots, audit, cache, resume -------------------------------------------------------------


class SpyBackend(OfflineBackend):
    def __init__(self, t):
        super().__init__(t)
        self.metric_queries = 0

    def metrics(self, *a, **kw):
        self.metric_queries += 1
        return super().metrics(*a, **kw)


def test_result_is_snapshotted_and_audited_before_it_is_returned():
    store = MemoryStore()
    layer = ToolLayer(store, OfflineBackend(tables()), None, "inv", scope(), "baseline")
    rec = layer.call("query_metrics", {"service": "orders", "metric": "lat", **W})
    stored = store.calls("inv")[rec.seq]
    assert stored is rec and rec.snapshot_id in store.snaps
    assert json.loads(store.snaps[rec.snapshot_id].content)["rows"] == rec.rows  # returned exactly as stored
    bad = layer.call("query_metrics", {"service": "batchjob", "metric": "lat", **W})
    assert store.calls("inv")[bad.seq].scope_decision == "rejected" and bad.snapshot_id is None


def test_cache_reuses_the_query_but_every_call_is_audited():
    be = SpyBackend(tables())
    store = MemoryStore()
    layer = ToolLayer(store, be, None, "inv", scope(), "baseline")
    a = layer.call("query_metrics", {"service": "orders", "metric": "lat", **W})
    b = layer.call("query_metrics", {"service": "orders", "metric": "lat", **W})
    assert be.metric_queries == 1 and (a.seq, b.seq) == (1, 2) and a.snapshot_id == b.snapshot_id


def test_resume_reuses_persisted_calls_and_detects_divergence():
    store = MemoryStore()
    first = ToolLayer(store, OfflineBackend(tables()), None, "inv", scope(), "baseline")
    first.call("query_metrics", {"service": "orders", "metric": "lat", **W})
    first.call("query_logs", {"service": "orders", **W})
    again = ToolLayer(store, SpyBackend(tables()), None, "inv", scope(), "baseline")  # after a restart
    assert again.call("query_metrics", {"service": "orders", "metric": "lat", **W}).seq == 1
    assert again.backend.metric_queries == 0 and len(store.calls("inv")) == 2  # nothing re-run or re-written
    with pytest.raises(RuntimeError, match="not deterministic"):
        again.call("query_logs", {"service": "payments", **W})


def test_a_second_ranker_continues_the_sequence():
    store = MemoryStore()
    ToolLayer(store, OfflineBackend(tables()), None, "inv", scope(), "baseline").call(
        "query_logs", {"service": "orders", **W}
    )
    agent = ToolLayer(store, OfflineBackend(tables()), None, "inv", scope(), "agent")
    assert agent.call("query_logs", {"service": "orders", **W}).seq == 2


# --- search_runbooks contamination rule (§12.2) --------------------------------------------------


def _vec(seed):
    h = hashlib.sha256(seed.encode()).digest()
    return [((h[i % 32] / 255.0) - 0.5) for i in range(768)]


def test_a_fixtures_own_postmortem_is_never_returned_while_it_is_evaluated(tmp_path):
    docs = [
        Doc("pm1", "Postmortem: pool_exhaustion_001", "postmortem", "pool_exhaustion_001", "inventory pool"),
        Doc("pm2", "Postmortem: pool_exhaustion_002", "postmortem", "pool_exhaustion_002", "inventory pool"),
        Doc("rb1", "Pool exhaustion", "runbook", None, "pools"),
    ]
    cassette = Cassette(tmp_path / "c.json")
    for d in docs:
        cassette.entries[cassette.key(d.text)] = {"text": d.text, "vector": _pack(_vec(d.id))}
    cassette.entries[cassette.key(query_text("pool"))] = {"text": "q", "vector": _pack(_vec("pm1"))}
    index = MemoryRunbookIndex(docs, cassette)
    sc = Scope(A, "gateway", ("gateway",), T0, T0, excluded_fixture="pool_exhaustion_001")
    d = execute(OfflineBackend(tables()), index, sc, "search_runbooks", {"query": "pool", "top_k": 5})
    assert [r["doc_id"] for r in d.rows] and "pm1" not in [r["doc_id"] for r in d.rows]
    assert "pm2" in [r["doc_id"] for r in d.rows]  # another fixture's postmortem may be returned
    unfiltered = execute(
        OfflineBackend(tables()),
        index,
        Scope(A, "gateway", ("gateway",), T0, T0),
        "search_runbooks",
        {"query": "pool", "top_k": 5},
    )
    assert unfiltered.rows[0]["doc_id"] == "pm1" and unfiltered.rows[0]["similarity"] == pytest.approx(1.0)


# --- outcome rules (§7.5) ------------------------------------------------------------------------


def h(service, kind, score, role="candidate_root_cause"):
    return {"causal_role": role, "cause_service": service, "cause_kind": kind, "score": score}


def test_outcome_rules_and_conflict_margin():
    assert outcome.decide([]) == "INSUFFICIENT_EVIDENCE"
    assert outcome.decide([h("orders", "latency", 0.9, "downstream_symptom")]) == "INSUFFICIENT_EVIDENCE"
    assert outcome.decide([h("inventory", "slow_query", 0.8)]) == "ROOT_CAUSE_IDENTIFIED"
    assert (
        outcome.decide([h("inventory", "slow_query", 0.8), h("payments", "dependency_outage", 0.71)])
        == "CONFLICTING_EVIDENCE"
    )
    assert (
        outcome.decide([h("inventory", "slow_query", 0.8), h("payments", "dependency_outage", 0.69)])
        == "ROOT_CAUSE_IDENTIFIED"
    )
    assert (
        outcome.decide([h("inventory", "slow_query", 0.8), h("inventory", "slow_query", 0.79)])
        == "ROOT_CAUSE_IDENTIFIED"
    )


def test_offline_edges_count_every_span_in_the_buckets_that_overlap_the_window():
    """A33: as ClickHouse's service_edges (bucket >= start's bucket AND bucket <= end), so a CLIENT span
    later in the last bucket counts; one in the next bucket does not; each span once (exact count)."""
    from investigation.backend import OfflineBackend

    def span(sid, ts):
        return {"tenant_id": A, "service": "orders", "span_id": sid, "start_ts": ts,
                "attrs": {"span.kind": "CLIENT", "peer.service": "payments"}}  # fmt: skip

    t = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
    spans = [span("a", t + timedelta(minutes=1)), span("a", t + timedelta(minutes=1)),
             span("b", t + timedelta(minutes=8)), span("c", t + timedelta(minutes=10))]  # fmt: skip
    edges = OfflineBackend({"spans": spans}).edges(A, t + timedelta(minutes=2), t + timedelta(minutes=6))
    assert edges == [("orders", "payments", 2)]  # a (once) and b (after end, same bucket); not c
