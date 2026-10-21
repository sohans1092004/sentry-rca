"""Over every recorded fixture, offline (Parquet backend, in-memory store):
- every gold claim, replayed as tool calls, passes the verifier (false-negative rate 0, §1.4);
- every out_of_scope_evidence citation is rejected by scope (A14);
- the baseline is deterministic: two runs give byte-identical hypotheses and tool requests."""

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from common.config import DEMO_TENANT_ID
from investigation import scope as scope_mod
from investigation import snapshots, verifier
from investigation.backend import OfflineBackend
from investigation.run import run_ranker
from investigation.tools import MemoryStore, ToolLayer
from recorder.dataset import TABLES, read_parquet

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("SENTRY_FIXTURES", ROOT / "data" / "fixtures"))
# the version each fixture is published at (fixtures/index.json); CI fetches exactly these
VERSIONS = {
    a["fixture_id"]: a["version"] for a in json.loads((ROOT / "fixtures" / "index.json").read_text())["fixtures"]
}
FIXTURES = sorted(f for f, v in VERSIONS.items() if (DATA / f / v / "label.json").exists())


@pytest.fixture(scope="module", params=FIXTURES)
def fixture(request):
    d = DATA / request.param / VERSIONS[request.param]
    tables = {t: read_parquet(d / f"{t}.parquet") for t in TABLES}
    inj = json.loads((d / "injection.json").read_text())
    manifest = json.loads((d / "manifest.json").read_text())
    inc = inj["incident"]
    incident = {
        "tenant_id": DEMO_TENANT_ID,
        "service": inc["service"],
        "first_anomaly_at": datetime.fromisoformat(inc["first_anomaly_at"]),
        "last_seen": datetime.fromisoformat(inc["last_seen"]),
    }
    window = (datetime.fromisoformat(manifest["window"][0]), datetime.fromisoformat(manifest["window"][1]))
    backend = OfflineBackend(tables)
    sc = scope_mod.compute(backend, incident, clamp=window, excluded_fixture=request.param)
    label = json.loads((d / "label.json").read_text())
    return request.param, backend, sc, label


def test_fixtures_present():
    assert FIXTURES, f"no fixture datasets under {DATA}: run `rca fixtures fetch`"


def test_every_gold_claim_passes_the_verifier(fixture):
    fid, backend, sc, label = fixture
    assert label["gold_claims"], f"{fid} has no in-scope gold claim"
    store = MemoryStore()
    layer = ToolLayer(store, backend, None, "gold", sc, "baseline")
    rejected = []
    for i, claim in enumerate(label["gold_claims"]):
        cites = [
            {"tool_call_seq": layer.call(c["tool"], c["args"]).seq, "row_ids": c["row_ids"]} for c in claim["cites"]
        ]
        r = verifier.verify_claim(i, {**claim, "cites": cites}, store.calls("gold"), "baseline", fid)
        if not r.passed:
            rejected.append(f"{claim['type']}: {r.reason}")
    assert rejected == [], rejected


def test_out_of_scope_evidence_is_rejected_by_scope(fixture):
    fid, backend, sc, label = fixture
    layer = ToolLayer(MemoryStore(), backend, None, "oos", sc, "baseline")
    for e in label.get("out_of_scope_evidence", []):
        for c in e["claim"]["cites"]:
            rec = layer.call(c["tool"], c["args"])
            assert rec.scope_decision == "rejected" and "outside scope" in rec.reason, (fid, c["args"])


def test_baseline_is_byte_identical_across_runs(fixture):
    fid, backend, sc, _ = fixture
    a, b = MemoryStore(), MemoryStore()
    ra = run_ranker(a, backend, None, "inv", sc)
    rb = run_ranker(b, backend, None, "inv", sc)
    assert snapshots.canonical(ra.hypotheses) == snapshots.canonical(rb.hypotheses)
    assert [c.requested for c in a.calls("inv").values()] == [c.requested for c in b.calls("inv").values()]
    assert ra.outcome == rb.outcome


@pytest.mark.parametrize("fid", ["bad_deploy_ambiguous_001"])
def test_ambiguous_fixture_finds_both_causes_and_applies_the_margin(fid):
    """Both injected causes are found and verified, and the outcome is exactly what the conflict margin
    (§7.5) decides from their scores. On v2 data this fixture came out CONFLICTING_EVIDENCE; on v3 the
    two causes score 0.35 apart, a measured result reported by the eval, not a property (ADR-006)."""
    d = DATA / fid / VERSIONS[fid]
    assert d.exists(), f"{fid} not present"
    tables = {t: read_parquet(d / f"{t}.parquet") for t in TABLES}
    inc = json.loads((d / "injection.json").read_text())["incident"]
    manifest = json.loads((d / "manifest.json").read_text())
    incident = {
        "tenant_id": DEMO_TENANT_ID,
        "service": inc["service"],
        "first_anomaly_at": datetime.fromisoformat(inc["first_anomaly_at"]),
        "last_seen": datetime.fromisoformat(inc["last_seen"]),
    }
    window = (datetime.fromisoformat(manifest["window"][0]), datetime.fromisoformat(manifest["window"][1]))
    backend = OfflineBackend(tables)
    sc = scope_mod.compute(backend, incident, clamp=window, excluded_fixture=fid)
    result = run_ranker(MemoryStore(), backend, None, "inv", sc)
    from investigation import outcome

    roots = [
        (h["cause_service"], h["cause_kind"]) for h in result.verified if h["causal_role"] == "candidate_root_cause"
    ]
    label = json.loads((d / "label.json").read_text())
    causes = {(label["root_cause"]["service"], label["root_cause"]["cause_kind"])}
    causes |= {(a["service"], a["cause_kind"]) for a in label["acceptable_alternatives"]}
    assert set(roots) & causes == causes, (roots, causes)  # both injected causes found and verified
    assert result.outcome == outcome.decide(result.verified), result.outcome
