"""Fixture labels v2 (Amendments A14, A19): same Parquet as v1, label rebuilt.

- gold_claims: only claims citable inside the fixture's own investigation scope. Each citation is run
  through the tool layer with that scope (offline, over the dataset); a claim with a rejected citation
  moves to out_of_scope_evidence, with the reason.
- planted_row_ids: the log rows an injection fixture planted (the decoy service's planted lines).

    python -m recorder.relabel [--dry-run] [fixture ...]
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from common.config import DEMO_TENANT_ID
from injector import scenarios
from investigation import scope as scope_mod
from investigation.backend import OfflineBackend
from investigation.tools import execute
from recorder import gold
from recorder.dataset import TABLES, read_parquet
from recorder.record import DATA, LABELS, make_label

SRC, DST = "v1", "v2"


def build(dataset: Path, fixture_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(label v2, report)."""
    tables = {t: read_parquet(dataset / f"{t}.parquet") for t in TABLES}
    inj = json.loads((dataset / "injection.json").read_text())
    manifest = json.loads((dataset / "manifest.json").read_text())
    run, inc = inj["run"], inj["incident"]
    incident = {
        "tenant_id": DEMO_TENANT_ID,
        "service": inc["service"],
        "first_anomaly_at": datetime.fromisoformat(inc["first_anomaly_at"]),
        "last_seen": datetime.fromisoformat(inc["last_seen"]),
    }
    window = (datetime.fromisoformat(manifest["window"][0]), datetime.fromisoformat(manifest["window"][1]))
    backend = OfflineBackend(tables)
    sc = scope_mod.compute(backend, incident, clamp=window, excluded_fixture=fixture_id)
    in_scope, out_of_scope = [], []
    for claim in gold.for_run(run, tables):
        rejected = [
            d.reason
            for c in claim["cites"]
            if (d := execute(backend, None, sc, c["tool"], c["args"])).decision == "rejected"
        ]
        if rejected:
            out_of_scope.append(
                {
                    "claim": claim,
                    "reason": f"no trace edge to the incident service {sc.incident_service}: {rejected[0]}",
                }
            )
        else:
            in_scope.append(claim)
    p = run["plan"]
    plan = scenarios.plan(p["scenario"], p["seed"], p["variant"])
    label = make_label(fixture_id, plan, in_scope)
    if out_of_scope:
        label["out_of_scope_evidence"] = out_of_scope
    planted = [(s.service, set(s.params["lines"])) for s in plan.steps if s.kind == "plant_logs"]
    if planted:
        label["planted_row_ids"] = sorted(
            str(r["log_id"])
            for r in tables["logs"]
            if any(r["service"] == svc and r["body"] in lines for svc, lines in planted)
        )
    report = {
        "fixture_id": fixture_id,
        "scope": list(sc.services),
        "gold": len(in_scope),
        "out_of_scope": len(out_of_scope),
        "planted_rows": len(label.get("planted_row_ids", [])),
    }
    return label, report


def main() -> None:
    dry = "--dry-run" in sys.argv
    ids = [a for a in sys.argv[1:] if not a.startswith("--")] or sorted(
        p.name for p in LABELS.iterdir() if (p / SRC / "label.json").exists()
    )
    for fid in ids:
        src = DATA / fid / SRC
        label, report = build(src, fid)
        print(json.dumps(report), "" if report["gold"] else "  <-- NO IN-SCOPE GOLD CLAIM", flush=True)
        if dry:
            continue
        dst = DATA / fid / DST
        dst.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.name != "label.json":
                shutil.copy2(f, dst / f.name)
        manifest = json.loads((dst / "manifest.json").read_text())
        manifest["version"] = DST
        (dst / "manifest.json").write_text(json.dumps(manifest, indent=2))
        (LABELS / fid / DST).mkdir(parents=True, exist_ok=True)
        for d in (dst, LABELS / fid / DST):
            (d / "label.json").write_text(json.dumps(label, indent=2, default=str))
            for f in ("injection.json", "manifest.json"):
                shutil.copy2(dst / f, d / f) if d != dst else None


if __name__ == "__main__":
    main()
