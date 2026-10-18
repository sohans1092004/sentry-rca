"""Fixture recorder (SPEC §3, §12.1): inject a scenario, wait for its incident, export the incident
window +- margin, label it, register it.

    python -m recorder.record campaign              # every fixture in CAMPAIGN not yet recorded
    python -m recorder.record one <fixture_id>
"""

import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from common import config, db
from injector import scenarios
from recorder import gold
from recorder.dataset import export, read_ch, read_deploys

PRE, POST = timedelta(minutes=15), timedelta(minutes=5)  # Amendment A7
ROOT = Path(__file__).resolve().parent.parent
DATA, LABELS, RUNS = ROOT / "data" / "fixtures", ROOT / "fixtures", ROOT / "runs"
VERSION = "v1"

# (fixture_id, scenario, seed, variant): every scenario; 3 multi-hop (pool_exhaustion), 3 ambiguous,
# 3 no-signal (no_fault), 2 noisy-neighbour, 2 injection (Phase 1 exit, Amendment A4).
CAMPAIGN: list[tuple[str, str, int, str | None]] = [
    ("pool_exhaustion_001", "pool_exhaustion", 1, None),
    ("bad_deploy_001", "bad_deploy", 1, None),
    ("no_fault_001", "no_fault", 1, None),
    ("slow_query_001", "slow_query", 1, None),
    ("dependency_outage_001", "dependency_outage", 1, None),
    ("noisy_neighbor_001", "noisy_neighbor", 1, None),
    ("memory_leak_001", "memory_leak", 1, None),
    ("slow_query_ambiguous_001", "slow_query", 1, "ambiguous"),
    ("dependency_outage_injection_001", "dependency_outage", 1, "injection"),
    ("pool_exhaustion_002", "pool_exhaustion", 2, None),
    ("no_fault_002", "no_fault", 2, None),
    ("bad_deploy_002", "bad_deploy", 2, None),
    ("bad_deploy_ambiguous_001", "bad_deploy", 1, "ambiguous"),
    ("noisy_neighbor_002", "noisy_neighbor", 2, None),
    ("slow_query_injection_002", "slow_query", 2, "injection"),
    ("pool_exhaustion_003", "pool_exhaustion", 3, None),
    ("no_fault_003", "no_fault", 3, None),
    ("dependency_outage_ambiguous_001", "dependency_outage", 1, "ambiguous"),
    ("slow_query_002", "slow_query", 2, None),
]


def _log(**f: Any) -> None:
    print(json.dumps({"ts": datetime.now(UTC).isoformat(timespec="seconds"), **f}, default=str), flush=True)


def _last_activity(pg: Any) -> datetime | None:
    times = [r["injection_end"] for f in RUNS.glob("*.json") if (r := json.loads(f.read_text())).get("injection_end")]
    last = [datetime.fromisoformat(t) for t in times]
    row = pg.execute("SELECT max(last_seen) FROM incidents").fetchone()
    if row and row[0]:
        last.append(row[0])
    return max(last) if last else None


def wait_quiet(pg: Any, ch: Any) -> None:
    """The pre-margin must hold only background traffic: no open incident, no fault and no incident
    activity for PRE, and at least PRE of telemetry in ClickHouse."""
    while True:
        now = datetime.now(UTC)
        open_ = pg.execute("SELECT count(*) FROM incidents WHERE status <> 'resolved'").fetchone()[0]
        last = _last_activity(pg)
        oldest = ch.query("SELECT min(ts) FROM metrics").result_rows[0][0]
        oldest = oldest.replace(tzinfo=UTC) if oldest and oldest.tzinfo is None else oldest
        quiet = open_ == 0 and (last is None or now - last >= PRE) and oldest and now - oldest >= PRE
        if quiet:
            return
        _log(event="waiting_quiet", open_incidents=open_, last_activity=last)
        time.sleep(30)


def _incidents_since(pg: Any, since: datetime) -> list[dict[str, Any]]:
    cur = pg.execute(
        "SELECT id::text, service, status, opened_at, first_anomaly_at, last_seen, alert_count, fingerprint "
        "FROM incidents WHERE opened_at >= %s ORDER BY opened_at", (since,))  # fmt: skip
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def record_one(fixture_id: str, scenario: str, seed: int, variant: str | None) -> dict[str, Any]:
    pg, ch = db.postgres(), db.clickhouse()
    wait_quiet(pg, ch)
    plan = scenarios.plan(scenario, seed, variant)
    _log(event="inject", fixture=fixture_id, delay_s=plan.delay_s)
    run = scenarios.run(plan, RUNS)
    start = datetime.fromisoformat(run["injection_start"])
    fault_start = min(datetime.fromisoformat(a["at"]) for a in run["applied"] if a["kind"] != "plant_logs")

    deadline = time.monotonic() + 15 * 60  # wait until every incident from this run has resolved
    while time.monotonic() < deadline:
        incs = _incidents_since(pg, start)
        if incs and all(i["status"] == "resolved" for i in incs):
            break
        time.sleep(15)
    incs = _incidents_since(pg, start)
    summary: dict[str, Any] = {"fixture_id": fixture_id, "scenario": scenario, "variant": variant, "seed": seed,
                               "run_id": run["run_id"], "fault_start": fault_start, "incidents": incs}  # fmt: skip
    if len(incs) != 1:
        _log(event="fixture_failed", reason=f"{len(incs)} incidents opened", **summary)
        return summary
    inc = incs[0]
    summary["alert_latency_s"] = (inc["opened_at"] - fault_start).total_seconds()
    summary["onset_to_open_s"] = (inc["opened_at"] - inc["first_anomaly_at"]).total_seconds()

    until = inc["last_seen"] + POST
    while datetime.now(UTC) < until + timedelta(seconds=20):  # + processor/flush lag
        time.sleep(10)
    w0, w1 = inc["first_anomaly_at"] - PRE, until
    tables = {t: read_ch(ch, t, config.DEMO_TENANT_ID, w0, w1) for t in ("metrics", "logs", "spans")}
    tables["deploys"] = read_deploys(pg, config.DEMO_TENANT_ID, w0 - timedelta(hours=1), w1)

    claims = []
    end = datetime.fromisoformat(run["injection_end"])
    for a in run["applied"]:
        if a["kind"] != "plant_logs":
            at = datetime.fromisoformat(a["at"])
            claims += gold.for_fault(a["kind"], a["service"], a["params"], at, min(end, at + timedelta(
                seconds=a["duration_s"])), tables)  # fmt: skip
    label = {
        "fixture_id": fixture_id, "scenario": scenario, "root_cause": plan.root_cause,
        "acceptable_alternatives": plan.acceptable_alternatives, "symptom_services": plan.symptom_services,
        "expected_outcome": plan.expected_outcome, "planted_injection": plan.planted_injection, "gold_claims": claims,
    }  # fmt: skip
    out = DATA / fixture_id / VERSION
    manifest = export(out, tables)
    manifest.update({"fixture_id": fixture_id, "version": VERSION, "window": [w0, w1]})
    injection = {"run": run, "incident": inc, "alert_latency_s": summary["alert_latency_s"],
                 "onset_to_open_s": summary["onset_to_open_s"], "variant": variant}  # fmt: skip
    labels_dir = LABELS / fixture_id / VERSION
    labels_dir.mkdir(parents=True, exist_ok=True)
    for d in (out, labels_dir):
        (d / "label.json").write_text(json.dumps(label, indent=2, default=str))
        (d / "injection.json").write_text(json.dumps(injection, indent=2, default=str))
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    pg.execute(
        "INSERT INTO fixtures (id, scenario, dataset_path, label) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (fixture_id, scenario, str(out.relative_to(ROOT)).replace("\\", "/"), json.dumps(label, default=str)),
    )
    summary.update({"recorded": True, "gold_claims": len(claims), "rows": {t: len(r) for t, r in tables.items()}})
    _log(event="fixture_recorded", **summary)
    return summary


def main() -> None:
    if sys.argv[1] == "one":
        [(fid, s, seed, v)] = [c for c in CAMPAIGN if c[0] == sys.argv[2]]
        record_one(fid, s, seed, v)
        return
    with (RUNS / "campaign.jsonl").open("a") as log:
        for fid, s, seed, v in CAMPAIGN:
            if (LABELS / fid / VERSION / "label.json").exists():
                continue
            result = record_one(fid, s, seed, v)
            log.write(json.dumps(result, default=str) + "\n")
            log.flush()


if __name__ == "__main__":
    RUNS.mkdir(exist_ok=True)
    main()
