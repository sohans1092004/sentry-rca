"""Deterministic verifier (SPEC §8.2, numeric rules A11, refinements A15/A18). No LLM, no tool calls:
it reads only the cited tool calls' snapshots.

Every check is one `_require(...)` so each can be named, tested and guard-checked on its own. A
claim fails at its first unmet check; a hypothesis with any failed claim is rejected.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from investigation.scope import parse
from investigation.tools import CallRecord

EPS = 1e-6
BASELINE = timedelta(minutes=15)
MAX_DEPLOY_GAP = timedelta(minutes=30)
ONSET_MATCH = timedelta(minutes=1)
RUNBOOK_MIN_SIMILARITY = 0.75
MAX_HOPS = 64
CLAIM_TOOLS = {
    "metric_change": {"query_metrics"},
    "log_pattern": {"query_logs"},
    "trace_dependency": {"query_traces"},
    "deploy_precedes_onset": {"get_recent_deploys", "get_incident_timeline"},
    "runbook_match": {"search_runbooks"},
}
ROLES = {"candidate_root_cause", "downstream_symptom"}


class Failed(Exception):
    pass


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise Failed(reason)


@dataclass
class ClaimResult:
    ordinal: int
    claim_type: str
    passed: bool
    reason: str | None
    citations: list[tuple[CallRecord, list[str]]] = field(default_factory=list)


@dataclass
class HypothesisResult:
    passed: bool
    reason: str | None
    claims: list[ClaimResult]

    @property
    def status(self) -> str:
        return "passed" if self.passed else "rejected"


def _ts(v: Any) -> datetime:
    return v if isinstance(v, datetime) else parse(str(v))


def _window(claim: dict[str, Any]) -> tuple[datetime, datetime]:
    w: Any = claim.get("window")
    _require(isinstance(w, list) and len(w) == 2, "window must be [start, end]")
    start, end = _ts(w[0]), _ts(w[1])
    _require(start <= end, "window starts after it ends")
    return start, end


def _cited(claim: dict[str, Any], calls: dict[int, CallRecord], ranker: str
           ) -> tuple[list[tuple[CallRecord, list[str]]], list[dict[str, Any]], list[dict[str, Any]]]:  # fmt: skip
    """Common checks (§8.2): returns (citations, cited rows, all rows of the cited snapshots)."""
    cites: Any = claim.get("cites")
    _require(isinstance(cites, list) and len(cites) > 0, "claim cites nothing")
    out: list[tuple[CallRecord, list[str]]] = []
    rows: list[dict[str, Any]] = []
    context: list[dict[str, Any]] = []
    for c in cites:
        _require(isinstance(c, dict) and isinstance(c.get("tool_call_seq"), int), "cite has no tool_call_seq")
        _require(isinstance(c.get("row_ids"), list) and len(c["row_ids"]) > 0, "cite has no row_ids")
        call = calls.get(c["tool_call_seq"])
        _require(call is not None, f"cites tool call {c['tool_call_seq']}, which is not in this investigation")
        assert call is not None
        _require(call.ranker == ranker, f"cites tool call {call.seq} of the {call.ranker} ranker")
        _require(call.scope_decision in ("allowed", "clamped"), f"cites tool call {call.seq}, which was rejected")
        _require(call.snapshot_id is not None, f"cited tool call {call.seq} has no snapshot")
        _require(call.tool_name in CLAIM_TOOLS[claim["type"]], f"a {claim['type']} claim cannot cite {call.tool_name}")
        by_id = {str(r["row_id"]): r for r in call.rows}
        for rid in c["row_ids"]:
            _require(str(rid) in by_id, f"row {rid} is not in the snapshot of tool call {call.seq}")
        out.append((call, [str(r) for r in c["row_ids"]]))
        rows.extend(by_id[str(r)] for r in c["row_ids"])
        context.extend(call.rows)
    return out, rows, context


def _metric_change(claim: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    start, end = _window(claim)
    _require(claim.get("direction") in ("up", "down"), "direction must be up or down")
    raw = claim.get("min_magnitude")
    _require(isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0, "min_magnitude must be >= 0")
    mm = float(raw)  # type: ignore[arg-type]
    for r in rows:
        _require(r.get("service") == claim.get("service"), f"cited row {r['row_id']} is from another service")
        _require(r.get("metric") == claim.get("metric"), f"cited row {r['row_id']} is another metric")
        _require(start - BASELINE <= _ts(r["ts"]) <= end, f"cited row {r['row_id']} is outside window and baseline")
    before = [float(r["value"]) for r in rows if start - BASELINE <= _ts(r["ts"]) < start]
    inside = [float(r["value"]) for r in rows if start <= _ts(r["ts"]) <= end]
    _require(len(before) >= 3, f"{len(before)} cited baseline points, need 3")
    _require(len(inside) >= 3, f"{len(inside)} cited window points, need 3")
    b, w = sum(before) / len(before), sum(inside) / len(inside)
    ratio = (w - b) / max(abs(b), EPS)
    if claim["direction"] == "up":
        _require(ratio >= mm, f"rose by {ratio:.6g}, claimed at least {mm}")
    else:
        _require(ratio <= -mm, f"changed by {ratio:.6g}, claimed a fall of at least {mm}")


def _log_pattern(claim: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    start, end = _window(claim)
    pattern, n = claim.get("pattern"), claim.get("min_count")
    _require(isinstance(pattern, str) and pattern != "", "pattern must be a non-empty string")
    _require(isinstance(n, int) and not isinstance(n, bool) and n >= 1, "min_count must be a positive integer")
    assert isinstance(pattern, str) and isinstance(n, int)
    for r in rows:
        _require(r.get("service") == claim.get("service"), f"cited row {r['row_id']} is from another service")
        _require(start <= _ts(r["ts"]) <= end, f"cited row {r['row_id']} is outside the window")
    hits = sum(1 for r in rows if pattern.lower() in str(r.get("body", "")).lower())
    _require(hits >= n, f"{hits} cited rows contain {pattern!r}, claimed {n}")


def _descends(child: dict[str, Any], ancestor: str, spans: dict[str, dict[str, Any]]) -> bool:
    node, hops = child, 0
    while node.get("parent_span_id") and hops < MAX_HOPS:
        if node["parent_span_id"] == ancestor:
            return True
        nxt = spans.get(node["parent_span_id"])
        if nxt is None:
            return False
        node, hops = nxt, hops + 1
    return False


def _trace_dependency(claim: dict[str, Any], rows: list[dict[str, Any]], context: list[dict[str, Any]]) -> None:
    parent_svc, child_svc = claim.get("parent_service"), claim.get("child_service")
    traces, share = claim.get("trace_ids"), claim.get("min_latency_share")
    _require(isinstance(traces, list) and len(traces) > 0, "trace_ids must be a non-empty list")
    _require(isinstance(share, (int, float)) and not isinstance(share, bool) and share >= 0, "bad min_latency_share")
    assert isinstance(traces, list) and isinstance(share, (int, float))
    for r in rows:
        _require(r.get("service") in (parent_svc, child_svc), f"cited span {r['row_id']} is from another service")
    for tid in traces:
        spans = {r["span_id"]: r for r in context if r.get("trace_id") == tid}
        parents = [r for r in rows if r.get("trace_id") == tid and r.get("service") == parent_svc]
        children = [r for r in rows if r.get("trace_id") == tid and r.get("service") == child_svc]
        _require(bool(parents) and bool(children), f"trace {tid}: no cited {parent_svc} and {child_svc} spans")
        pairs = [(p, c) for p in parents for c in children if _descends(c, p["span_id"], spans)]
        _require(bool(pairs), f"trace {tid}: no cited {child_svc} span descends from a cited {parent_svc} span")
        best = max(float(c["duration_ms"]) / float(p["duration_ms"]) for p, c in pairs if float(p["duration_ms"]) > 0)
        _require(best >= share, f"trace {tid}: child share {best:.6g}, claimed at least {share}")


def _deploy_precedes_onset(claim: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    svc, did = claim.get("service"), claim.get("deploy_id")
    onset = _ts(claim.get("onset_ts"))
    deploys = [r for r in rows if r.get("row_id") == did or (r.get("kind") == "deploy" and r.get("deploy_id") == did)]
    _require(bool(deploys), f"deploy {did} is not cited")
    d = deploys[0]
    _require(d.get("service") == svc, f"deploy {did} is for {d.get('service')}, not {svc}")
    finished = _ts(d["finished_at"] if "finished_at" in d else d["ts"])
    _require(finished < onset, f"deploy finished at {finished.isoformat()}, not before the onset")
    _require(onset - finished <= MAX_DEPLOY_GAP, f"deploy finished {onset - finished} before the onset, over the gap")
    onsets = [r for r in rows if r.get("kind") == "anomaly_onset" and r.get("service") == svc]
    _require(any(abs(_ts(r["ts"]) - onset) <= ONSET_MATCH for r in onsets),
             f"no cited anomaly onset of {svc} within 1 minute of {onset.isoformat()}")  # fmt: skip


def _runbook_match(claim: dict[str, Any], rows: list[dict[str, Any]], excluded_fixture: str | None) -> None:
    sim = claim.get("similarity")
    _require(isinstance(sim, (int, float)) and not isinstance(sim, bool), "similarity must be a number")
    assert isinstance(sim, (int, float))
    docs = [r for r in rows if r.get("row_id") == claim.get("doc_id")]
    _require(bool(docs), f"runbook {claim.get('doc_id')} is not cited")
    d = docs[0]
    _require(float(d["similarity"]) >= sim, f"similarity {d['similarity']:.6g} is below the claimed {sim}")
    _require(float(d["similarity"]) >= RUNBOOK_MIN_SIMILARITY,
             f"similarity {d['similarity']:.6g} is below runbook_min_similarity {RUNBOOK_MIN_SIMILARITY}")  # fmt: skip
    own = d.get("kind") == "postmortem" and d.get("fixture_id") is not None and d.get("fixture_id") == excluded_fixture
    _require(not own, "cites the evaluated fixture's own postmortem")


def verify_claim(ordinal: int, claim: dict[str, Any], calls: dict[int, CallRecord], ranker: str,
                 excluded_fixture: str | None = None) -> ClaimResult:  # fmt: skip
    kind = str(claim.get("type"))
    try:
        _require(kind in CLAIM_TOOLS, f"unknown claim type {kind}")
        citations, rows, context = _cited(claim, calls, ranker)
        if kind == "metric_change":
            _metric_change(claim, rows)
        elif kind == "log_pattern":
            _log_pattern(claim, rows)
        elif kind == "trace_dependency":
            _trace_dependency(claim, rows, context)
        elif kind == "deploy_precedes_onset":
            _deploy_precedes_onset(claim, rows)
        else:
            _runbook_match(claim, rows, excluded_fixture)
    except Failed as e:
        return ClaimResult(ordinal, kind, False, str(e))
    except (KeyError, TypeError, ValueError) as e:
        return ClaimResult(ordinal, kind, False, f"malformed claim: {type(e).__name__}: {e}")
    return ClaimResult(ordinal, kind, True, None, citations)


def verify(hypothesis: dict[str, Any], calls: dict[int, CallRecord], ranker: str,
           excluded_fixture: str | None = None) -> HypothesisResult:  # fmt: skip
    claims = hypothesis.get("claims")
    if not isinstance(claims, list) or not claims:
        return HypothesisResult(False, "a hypothesis needs at least one claim", [])
    results = [verify_claim(i, c, calls, ranker, excluded_fixture) for i, c in enumerate(claims)]
    if hypothesis.get("causal_role") not in ROLES:
        return HypothesisResult(False, f"unknown causal_role {hypothesis.get('causal_role')}", results)
    if hypothesis["causal_role"] == "candidate_root_cause" and all(c.get("type") == "runbook_match" for c in claims):
        return HypothesisResult(False, "a root cause needs evidence beyond a similar past incident", results)
    failed = [r for r in results if not r.passed]
    if failed:
        return HypothesisResult(False, f"claim {failed[0].ordinal} failed: {failed[0].reason}", results)
    return HypothesisResult(True, None, results)
