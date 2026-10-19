"""Fixture recorder (SPEC §3, §12.1): inject a scenario, wait for its incident, export the incident
window +- margin, label it, register it.

    python -m recorder.record campaign [dev|test]     # every fixture of that split not yet recorded
    python -m recorder.record one <fixture_id>

v3 (Amendments A21-A22): faults surface through normal code paths; about half the fixtures carry
confounders (a harmless deploy, a mild unrelated anomaly, log and trace sampling). Labels are built
here in one pass: in-scope gold claims, out_of_scope_evidence, planted_row_ids, the confounders and
whether each lies inside the investigation scope.
"""

import hashlib
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from common import config, db, deploys
from injector import scenarios
from recorder import gold
from recorder.dataset import export, read_ch

PRE, POST = timedelta(minutes=15), timedelta(minutes=5)  # Amendment A7
ROOT = Path(__file__).resolve().parent.parent
DATA, LABELS, RUNS = ROOT / "data" / "fixtures", ROOT / "fixtures", ROOT / "runs"
VERSION = "v3"


# (fixture_id, scenario, seed, variant, partner, confounded). Dev: the 19 Phase 1 fixtures, re-recorded,
# every other one confounded. Test (A22): never used to develop the baseline or prompts.
Entry = tuple[str, str, int, str | None, str | None, bool]
DEV: list[Entry] = [
    ("pool_exhaustion_001", "pool_exhaustion", 1, None, None, False),
    ("bad_deploy_001", "bad_deploy", 1, None, None, True),
    ("no_fault_001", "no_fault", 1, None, None, False),
    ("slow_query_001", "slow_query", 1, None, None, True),
    ("dependency_outage_001", "dependency_outage", 1, None, None, False),
    ("noisy_neighbor_001", "noisy_neighbor", 1, None, None, True),
    ("memory_leak_001", "memory_leak", 1, None, None, False),
    ("slow_query_ambiguous_001", "slow_query", 1, "ambiguous", None, True),
    ("dependency_outage_injection_001", "dependency_outage", 1, "injection", None, False),
    ("pool_exhaustion_002", "pool_exhaustion", 2, None, None, True),
    ("no_fault_002", "no_fault", 2, None, None, False),
    ("bad_deploy_002", "bad_deploy", 2, None, None, True),
    ("bad_deploy_ambiguous_001", "bad_deploy", 1, "ambiguous", None, False),
    ("noisy_neighbor_002", "noisy_neighbor", 2, None, None, True),
    ("slow_query_injection_002", "slow_query", 2, "injection", None, False),
    ("pool_exhaustion_003", "pool_exhaustion", 3, None, None, True),
    ("no_fault_003", "no_fault", 3, None, None, False),
    ("dependency_outage_ambiguous_001", "dependency_outage", 1, "ambiguous", None, True),
    ("slow_query_002", "slow_query", 2, None, None, False),
]
TEST: list[Entry] = [
    ("config_change_t01", "config_change", 101, None, None, False),
    ("cache_stampede_t01", "cache_stampede", 101, None, None, True),
    ("connection_refused_t01", "connection_refused", 101, None, None, False),
    ("cpu_throttling_t01", "cpu_throttling", 101, None, None, True),
    ("ambiguous_t01", "bad_deploy", 101, "ambiguous", "slow_query", True),
    ("pool_exhaustion_t01", "pool_exhaustion", 101, None, None, True),
    ("config_change_t02", "config_change", 102, None, None, True),
    ("cache_stampede_t02", "cache_stampede", 102, None, None, False),
    ("ambiguous_t02", "dependency_outage", 101, "ambiguous", "connection_refused", False),
    ("memory_leak_t01", "memory_leak", 101, None, None, False),
    ("connection_refused_t02", "connection_refused", 102, None, None, True),
    ("cpu_throttling_t02", "cpu_throttling", 102, None, None, False),
    ("no_fault_t01", "no_fault", 101, None, None, True),
    ("ambiguous_t03", "cpu_throttling", 101, "ambiguous", "cache_stampede", True),
    ("bad_deploy_t01", "bad_deploy", 101, None, None, False),
    ("noisy_neighbor_t01", "noisy_neighbor", 101, None, None, False),
    ("slow_query_injection_t01", "slow_query", 101, "injection", None, True),
]
SPLITS = {"dev": DEV, "test": TEST}


def split_of(fixture_id: str) -> str:
    return next(s for s, entries in SPLITS.items() if any(e[0] == fixture_id for e in entries))


def make_label(fixture_id: str, plan: scenarios.Plan, claims: list[dict[str, Any]]) -> dict[str, Any]:
    """label.json in the SPEC §3 schema, plus `notes` when the scenario has one (Amendment A13)."""
    label = {
        "fixture_id": fixture_id, "scenario": plan.scenario, "root_cause": plan.root_cause,
        "acceptable_alternatives": plan.acceptable_alternatives, "symptom_services": plan.symptom_services,
        "expected_outcome": plan.expected_outcome, "planted_injection": plan.planted_injection, "gold_claims": claims,
    }  # fmt: skip
    if plan.notes:
        label["notes"] = plan.notes
    return label


def _kept(key: str, fraction: float) -> bool:
    """Deterministic head sampling: keep `key` when its hash falls in the first `fraction`."""
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") < fraction * 2**64


def sample(tables: dict[str, list[dict[str, Any]]], sampling: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """G1: what a sampler at the source would have stored. Whole traces by trace_id; logs one by one."""
    return {**tables, "spans": [s for s in tables["spans"] if _kept(s["trace_id"], sampling["traces"])],
            "logs": [r for r in tables["logs"] if _kept(str(r["log_id"]), sampling["logs"])]}  # fmt: skip


Tables = dict[str, list[dict[str, Any]]]


def build_label(fixture_id: str, plan: scenarios.Plan, run: dict[str, Any], incident: dict[str, Any],
                tables: Tables, window: tuple[datetime, datetime]) -> dict[str, Any]:  # fmt: skip
    from investigation import scope as scope_mod
    from investigation.backend import OfflineBackend
    from investigation.tools import execute

    backend = OfflineBackend(tables)
    inc = {"tenant_id": config.DEMO_TENANT_ID, **{k: incident[k] for k in ("service", "first_anomaly_at", "last_seen")}}
    sc = scope_mod.compute(backend, inc, clamp=window, excluded_fixture=fixture_id)
    in_scope, out_of_scope = [], []
    for claim in gold.for_run(run, tables):
        rejected = [d.reason for c in claim["cites"]
                    if (d := execute(backend, None, sc, c["tool"], c["args"])).decision == "rejected"]  # fmt: skip
        if rejected:
            out_of_scope.append({"claim": claim, "reason": f"no trace edge to the incident service "
                                                           f"{sc.incident_service}: {rejected[0]}"})  # fmt: skip
        else:
            in_scope.append(claim)
    label = make_label(fixture_id, plan, in_scope)
    label["split"] = split_of(fixture_id)
    if out_of_scope:
        label["out_of_scope_evidence"] = out_of_scope
    planted = [line for s in plan.steps if s.kind == "plant" for line in s.params["lines"]]
    if planted:
        label["planted_row_ids"] = sorted(
            str(r["log_id"]) for r in tables["logs"] if any(p in r["body"] for p in planted)
        )
    label["sampling"] = plan.sampling
    label["confounders"] = [
        {"kind": a["kind"], "service": a["service"], "at": a["at"], "in_scope": a["service"] in sc.services}
        for a in run["applied"] if a["role"] == "confounder"
    ]  # fmt: skip
    label["scope_services"] = list(sc.services)
    return label


class DirtyStart(Exception):
    pass


def _log(**f: Any) -> None:
    print(json.dumps({"ts": datetime.now(UTC).isoformat(timespec="seconds"), **f}, default=str), flush=True)


def _last_activity(pg: Any) -> datetime | None:
    times = [r["injection_end"] for f in RUNS.glob("*.json") if (r := json.loads(f.read_text())).get("injection_end")]
    last = [datetime.fromisoformat(t) for t in times]
    row = pg.execute("SELECT max(last_seen) FROM incidents").fetchone()
    if row and row[0]:
        last.append(row[0])
    return max(last) if last else None


def alert_baseline(pg: Any) -> timedelta:
    """How far back the alert rules look at a fault's start: their window plus the latency baseline."""
    rows = pg.execute("SELECT condition FROM alert_rules WHERE enabled").fetchall()
    return max((timedelta(seconds=c["window_s"] + max((x.get("baseline_s", 0) for x in c["any_of"]), default=0))
                for (c,) in rows), default=timedelta(0))  # fmt: skip


def incident_in_baseline(pg: Any, now: datetime) -> str | None:
    """A29: why `now` is not a clean fault start, or None. No incident may be open, and none of an
    incident's period (first anomaly to resolution, last_seen + RESOLVE_AFTER) may lie in the alert
    baseline window before `now`."""
    from alerting.engine import RESOLVE_AFTER

    open_ = pg.execute("SELECT count(*) FROM incidents WHERE status <> 'resolved'").fetchone()[0]
    if open_:
        return f"{open_} incidents open"
    since = now - alert_baseline(pg)
    row = pg.execute("SELECT count(*), max(last_seen) + %s FROM incidents WHERE last_seen + %s > %s AND "
                     "fingerprint NOT LIKE 'eval:%%'", (RESOLVE_AFTER, RESOLVE_AFTER, since)).fetchone()  # fmt: skip
    return f"{row[0]} incidents in the alert baseline (last resolved {row[1]})" if row[0] else None


def wait_quiet(pg: Any, ch: Any) -> None:
    """The pre-margin must hold only background traffic: no open incident, no fault and no incident
    activity for PRE, at least PRE of telemetry in ClickHouse, and (A29) no incident period anywhere in
    the alert baseline the fault will be judged against."""
    while True:
        now = datetime.now(UTC)
        last = _last_activity(pg)
        oldest = ch.query("SELECT min(ts) FROM metrics").result_rows[0][0]
        oldest = oldest.replace(tzinfo=UTC) if oldest and oldest.tzinfo is None else oldest
        dirty = incident_in_baseline(pg, now)
        quiet = dirty is None and (last is None or now - last >= PRE) and oldest and now - oldest >= PRE
        if quiet:
            return
        _log(event="waiting_quiet", baseline=dirty, last_activity=last)
        time.sleep(30)


def _incidents_since(pg: Any, since: datetime) -> list[dict[str, Any]]:
    cur = pg.execute(
        "SELECT id::text, service, status, opened_at, first_anomaly_at, last_seen, alert_count, fingerprint "
        "FROM incidents WHERE opened_at >= %s ORDER BY opened_at", (since,))  # fmt: skip
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def record_one(entry: Entry) -> dict[str, Any]:
    fixture_id, scenario, seed, variant, partner, confounded = entry
    pg, ch = db.postgres(), db.clickhouse()
    wait_quiet(pg, ch)
    quiet_until = datetime.now(UTC)
    plan = scenarios.plan(scenario, seed, variant, partner, confounded)
    _log(event="inject", fixture=fixture_id, delay_s=plan.delay_s, confounded=confounded)

    def clean_start() -> None:  # A29: checked again at the moment the first fault is applied
        if (why := incident_in_baseline(pg, datetime.now(UTC))) is not None:
            raise DirtyStart(why)

    try:
        run = scenarios.run(plan, RUNS, precheck=clean_start)
    except DirtyStart as e:
        _log(event="fixture_failed", fixture_id=fixture_id, reason=f"not a clean fault start: {e}")
        return {"fixture_id": fixture_id, "recorded": False, "error": f"not a clean fault start: {e}"}
    fault_start = min(datetime.fromisoformat(a["at"]) for a in run["applied"] if a["role"] == "cause")

    deadline = time.monotonic() + 15 * 60  # wait until every incident from this run has resolved
    while time.monotonic() < deadline:
        incs = _incidents_since(pg, quiet_until)
        if incs and all(i["status"] == "resolved" for i in incs):
            break
        time.sleep(15)
    # Counted from the end of the quiet window, not the injection: an incident that opened during the
    # random pre-injection delay would otherwise absorb this fault through dedup, unseen.
    incs = _incidents_since(pg, quiet_until)
    summary: dict[str, Any] = {"fixture_id": fixture_id, "scenario": scenario, "variant": variant, "seed": seed,
                               "partner": partner, "confounded": confounded, "run_id": run["run_id"],
                               "fault_start": fault_start, "incidents": incs}  # fmt: skip
    early = [i for i in incs if i["first_anomaly_at"] < fault_start]
    if len(incs) != 1 or early:
        reason = f"{len(incs)} incidents opened" + (f", {len(early)} before the fault started" if early else "")
        _log(event="fixture_failed", reason=reason, **summary)
        return summary
    inc = incs[0]
    summary["alert_latency_s"] = (inc["opened_at"] - fault_start).total_seconds()
    summary["onset_to_open_s"] = (inc["opened_at"] - inc["first_anomaly_at"]).total_seconds()

    until = inc["last_seen"] + POST
    while datetime.now(UTC) < until + timedelta(seconds=20):  # + processor/flush lag
        time.sleep(10)
    w0, w1 = inc["first_anomaly_at"] - PRE, until
    tables = {t: read_ch(ch, t, config.DEMO_TENANT_ID, w0, w1) for t in ("metrics", "logs", "spans")}
    tables["deploys"] = deploys.recent(ch, config.DEMO_TENANT_ID, w0 - timedelta(hours=1), w1)
    if plan.sampling:
        tables = sample(tables, plan.sampling)

    label = build_label(fixture_id, plan, run, inc, tables, (w0, w1))
    out = DATA / fixture_id / VERSION
    manifest = export(out, tables)
    manifest.update({"fixture_id": fixture_id, "version": VERSION, "window": [w0, w1]})
    injection = {"run": run, "incident": inc, "alert_latency_s": summary["alert_latency_s"],
                 "onset_to_open_s": summary["onset_to_open_s"], "variant": variant, "partner": partner}  # fmt: skip
    labels_dir = LABELS / fixture_id / VERSION
    labels_dir.mkdir(parents=True, exist_ok=True)
    for d in (out, labels_dir):
        (d / "label.json").write_text(json.dumps(label, indent=2, default=str))
        (d / "injection.json").write_text(json.dumps(injection, indent=2, default=str))
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    pg.execute(
        "INSERT INTO fixtures (id, scenario, dataset_path, label) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET dataset_path = EXCLUDED.dataset_path, label = EXCLUDED.label",
        (fixture_id, scenario, str(out.relative_to(ROOT)).replace("\\", "/"), json.dumps(label, default=str)),
    )
    outside = [c for c in label["confounders"] if not c["in_scope"]]
    summary.update({"recorded": True, "gold_claims": len(label["gold_claims"]), "confounders_outside_scope": outside,
                    "rows": {t: len(r) for t, r in tables.items()}})  # fmt: skip
    _log(event="fixture_recorded", **summary)
    return summary


def main() -> None:
    if sys.argv[1] == "one":
        [entry] = [e for e in DEV + TEST if e[0] == sys.argv[2]]
        record_one(entry)
        return
    split = sys.argv[2] if len(sys.argv) > 2 else "dev"
    with (RUNS / f"campaign-{VERSION}-{split}.jsonl").open("a") as log:
        for entry in SPLITS[split]:
            if (LABELS / entry[0] / VERSION / "label.json").exists():
                continue
            try:
                result = record_one(entry)
            except Exception as e:  # one broken fixture must not end an overnight campaign
                result = {"fixture_id": entry[0], "recorded": False, "error": f"{type(e).__name__}: {e}"[:500]}
                _log(event="fixture_failed", **result)
            log.write(json.dumps(result, default=str) + "\n")
            log.flush()


if __name__ == "__main__":
    RUNS.mkdir(exist_ok=True)
    main()
