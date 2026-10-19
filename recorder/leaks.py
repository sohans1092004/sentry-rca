"""Leak test (Amendment A28): can a fixture's telemetry name its scenario by itself?

Across all fixtures, every *item* is listed: a log template (the logging call's file, function and line,
with severity), a log or span attribute key and, for low-cardinality keys, its values, a span name and
status, a metric name with its label keys and low-cardinality values, and the shape of a deploy version.
Each occurrence is attributed to a context: `healthy` (before anything was injected), the scenario of
a fault step (until 2 minutes after it ends), a confounder kind, or the planted lines.

An item never seen in healthy traffic is listed. It fails the test when it appears with faults of only
one scenario and no confounder (it identifies that scenario), or with confounders only (it tells a
confounder from a real cause). Planted rows are excluded: their text is the attack, meant to be seen.

    python -m recorder.leaks [fixture_dir ...]      # default: every v3 dataset under data/fixtures
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from recorder.dataset import TABLES, read_parquet

ROOT = Path(__file__).resolve().parent.parent
TAIL = timedelta(minutes=2)
MAX_VALUES = 30  # a key with more distinct values is an identifier (ids, timestamps), not vocabulary
HIGH_CARDINALITY = {"code.line.number", "net.peer.port", "http.target", "http.url", "url.full", "url.path"}
# what each applied fault step means, for attribution (v3 kinds, A21-A22)
STEP_SCENARIO = {"lock_wait": "slow_query", "conn_leak": "pool_exhaustion", "bad_deploy": "bad_deploy",
                 "dependency_outage": "dependency_outage", "memory_leak": "memory_leak", "cpu_burn": "noisy_neighbor",
                 "jitter": "no_fault", "config_change": "config_change", "cache_stampede": "cache_stampede",
                 "refused": "connection_refused", "cpu_quota": "cpu_throttling"}  # fmt: skip

Item = tuple[str, ...]
Context = tuple[str, str]  # ("healthy", ""), ("cause", scenario), ("confounder", kind), ("plant", "")


def _items(table: str, r: dict[str, Any]) -> list[tuple[Item, str | None, str | None]]:
    """(item, key for the cardinality count, value) per row; value items are kept only if the key is low-card."""
    out: list[tuple[Item, str | None, str | None]] = []
    svc = r.get("service", "")
    if table == "logs":
        a = r["attrs"]
        out.append((("log_template", svc, a.get("code.file.path", ""), a.get("code.function.name", ""),
                     a.get("code.line.number", ""), r["severity"]), None, None))  # fmt: skip
        for k, v in a.items():
            out.append((("log_attr_key", svc, k), None, None))
            out.append((("log_attr", svc, k, v), f"log:{k}", v))
    elif table == "spans":
        out.append((("span_name", svc, r["name"]), None, None))
        out.append((("span_status", svc, r["status"]), None, None))
        for k, v in r["attrs"].items():
            out.append((("span_attr_key", svc, k), None, None))
            out.append((("span_attr", svc, k, v), f"span:{k}", v))
    elif table == "metrics":
        out.append((("metric", svc, r["metric"]), None, None))
        for k, v in r["labels"].items():
            out.append((("metric_label_key", svc, r["metric"], k), None, None))
            out.append((("metric_label", svc, r["metric"], k, v), f"metric:{r['metric']}:{k}", v))
    elif table == "deploys":
        out.append(
            (("deploy_version_shape", re.sub(r"[a-z]+-", "<svc>-", re.sub(r"\d+", "#", r["version"]))), None, None)
        )
    return out


def _contexts(ts: datetime, steps: list[dict[str, Any]], scenario: str) -> set[Context]:
    first = min(s["at"] for s in steps)
    if ts < first:
        return {("healthy", "")}
    found = set()
    for s in steps:
        if s["at"] <= ts <= s["end"] + TAIL:
            if s["role"] == "plant":
                found.add(("plant", ""))
            elif s["role"] == "confounder":
                found.add(("confounder", s["kind"]))
            else:
                found.add(("cause", STEP_SCENARIO.get(s["kind"], s["kind"])))
    return found or {("cause", scenario)}  # recovery after every step ended: still this fixture's fault


def _steps(injection: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for a in injection["run"]["applied"]:
        at = datetime.fromisoformat(a["at"])
        out.append({"at": at, "end": at + timedelta(seconds=a["duration_s"]), "kind": a["kind"],
                    "role": a.get("role", "plant" if a["kind"] == "plant_logs" else "cause")})  # fmt: skip
    for key in ("deploy_row", "confounder_deploy_row"):  # a deploy row is an event at its finish time
        if row := injection["run"].get(key):
            at = datetime.fromisoformat(row["finished_at"])
            out.append({"at": at, "end": at, "kind": "deploy" if key.startswith("conf") else "bad_deploy",
                        "role": "confounder" if key.startswith("conf") else "cause"})  # fmt: skip
    return out


def audit(datasets: list[Path]) -> dict[str, Any]:
    seen: dict[Item, set[Context]] = defaultdict(set)
    where: dict[Item, set[str]] = defaultdict(set)
    values: dict[str, set[str]] = defaultdict(set)
    value_items: dict[Item, str] = {}
    for d in datasets:
        label = json.loads((d / "label.json").read_text())
        injection = json.loads((d / "injection.json").read_text())
        steps, planted = _steps(injection), set(label.get("planted_row_ids", []))
        for table, spec in TABLES.items():
            for r in read_parquet(d / f"{table}.parquet"):
                if table == "logs" and str(r["log_id"]) in planted:
                    continue
                ctx = _contexts(r[spec["time"]], steps, label["scenario"])
                for item, key, value in _items(table, r):
                    if key is not None:
                        if key.split(":")[-1] in HIGH_CARDINALITY:
                            continue
                        values[key].add(str(value))
                        value_items[item] = key
                    seen[item] |= ctx
                    where[item].add(label["fixture_id"])
    listed, failures = [], []
    for item, ctx in sorted(seen.items()):
        if item in value_items and len(values[value_items[item]]) > MAX_VALUES:
            continue
        if ("healthy", "") in ctx:
            continue
        scenarios = sorted({c[1] for c in ctx if c[0] == "cause"})
        confounders = sorted({c[1] for c in ctx if c[0] == "confounder"})
        entry = {"item": list(item), "scenarios": scenarios, "confounders": confounders,
                 "plant": ("plant", "") in ctx, "fixtures": sorted(where[item])}  # fmt: skip
        listed.append(entry)
        if len(scenarios) == 1 and not confounders:
            failures.append({**entry, "why": f"identifies scenario {scenarios[0]}"})
        elif confounders and not scenarios:
            failures.append({**entry, "why": f"tells confounder {', '.join(confounders)} from a real cause"})
    return {"datasets": len(datasets), "items": len(seen), "never_healthy": listed, "failures": failures}


def v3_datasets() -> list[Path]:
    return sorted(p for p in (ROOT / "data" / "fixtures").glob("*/v3") if (p / "label.json").exists())


if __name__ == "__main__":
    paths = [Path(a) for a in sys.argv[1:]] or v3_datasets()
    report = audit(paths)
    print(json.dumps({k: report[k] for k in ("datasets", "items")}))
    for e in report["never_healthy"]:
        print("never healthy:", json.dumps(e))
    for f in report["failures"]:
        print("LEAK:", json.dumps(f))
    sys.exit(1 if report["failures"] else 0)
