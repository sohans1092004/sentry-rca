"""Smoke run of the v3 faults (Amendments A21-A22) on the live stack: each case, shortened to 2 minutes,
must open exactly one incident; the confounders alone must open none. Not a fixture: nothing is
exported or labelled.

    uv run python tools/smoke_faults.py [case ...]
"""

import json
import sys
import time
from datetime import UTC, datetime
from typing import Any

from common import db
from injector import scenarios

FAULT_S = 120
CASES: dict[str, tuple[str, int, str | None, str | None]] = {
    "slow_query_orders": ("slow_query", 3, None, None),
    "slow_query_inventory": ("slow_query", 1, None, None),
    "pool_exhaustion": ("pool_exhaustion", 1, None, None),
    "bad_deploy_slow": ("bad_deploy", 1, None, None),
    "bad_deploy_errors": ("bad_deploy", 2, None, None),
    "dependency_outage": ("dependency_outage", 1, None, None),
    "config_change": ("config_change", 1, None, None),
    "cache_stampede": ("cache_stampede", 1, None, None),
    "connection_refused": ("connection_refused", 1, None, None),
    "cpu_throttling": ("cpu_throttling", 1, None, None),
    "confounders_only": ("no_fault", 1, None, None),
}


def _log(**f: Any) -> None:
    print(json.dumps({"ts": datetime.now(UTC).isoformat(timespec="seconds"), **f}, default=str), flush=True)


def _wait_resolved(pg: Any) -> None:
    while pg.execute("SELECT count(*) FROM incidents WHERE status <> 'resolved'").fetchone()[0]:
        time.sleep(15)


def smoke(name: str) -> dict[str, Any]:
    scenario, seed, variant, partner = CASES[name]
    pg = db.postgres()
    _wait_resolved(pg)
    if name == "confounders_only":  # the confounders of a confounded plan, around a fault that does nothing
        p = scenarios.plan(scenario, seed, variant, partner, confounded=True)
        p.steps = [s for s in p.steps if s.role == "confounder"]
        p.steps.append(scenarios.Step(0, "gateway", "jitter", {"p": 0, "max_ms": 0}, 60))
    else:
        p = scenarios.plan(scenario, seed, variant, partner)
    p.delay_s = 5
    for s in p.steps:
        if s.role == "cause":
            s.duration_s = min(s.duration_s, FAULT_S)
    since = datetime.now(UTC)
    run = scenarios.run(p)
    time.sleep(60)  # alert windows still closing
    rows = pg.execute("SELECT opened_at, first_anomaly_at, service FROM incidents WHERE opened_at >= %s",
                      (since,)).fetchall()  # fmt: skip
    cause = [datetime.fromisoformat(a["at"]) for a in run["applied"] if a["role"] == "cause"]
    out = {"case": name, "steps": [(a["kind"], a["service"], a["role"]) for a in run["applied"]],
           "incidents": len(rows), "alert_latency_s": [round((r[0] - min(cause)).total_seconds(), 1) for r in rows],
           "ok": len(rows) == (0 if name == "confounders_only" else 1)}  # fmt: skip
    _log(**out)
    return out


if __name__ == "__main__":
    results = [smoke(n) for n in (sys.argv[1:] or list(CASES))]
    _log(summary={r["case"]: r["ok"] for r in results})
