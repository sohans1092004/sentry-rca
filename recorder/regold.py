"""Rebuild labels for recorded fixtures from their own datasets and their (seeded) plans, with the
same code record_one uses: gold claims from the Parquet rows, everything else from the plan.

python -m recorder.regold [fixture_id ...]     # default: every fixture under fixtures/
"""

import json
import sys

from common import db
from injector import scenarios
from recorder import gold
from recorder.dataset import TABLES, read_parquet
from recorder.record import DATA, LABELS, make_label

VERSION = "v1"  # regold rewrote the Phase 1 labels; v3 labels are built by record.py itself


def regold(fixture_id: str) -> int:
    data = DATA / fixture_id / VERSION
    run = json.loads((data / "injection.json").read_text())["run"]
    tables = {t: read_parquet(data / f"{t}.parquet") for t in TABLES}
    p = run["plan"]
    plan = scenarios.plan(p["scenario"], p["seed"], p["variant"])
    label = make_label(fixture_id, plan, gold.for_run(run, tables))
    for d in (data, LABELS / fixture_id / VERSION):
        (d / "label.json").write_text(json.dumps(label, indent=2, default=str))
    with db.postgres() as pg:
        pg.execute("UPDATE fixtures SET label = %s WHERE id = %s", (json.dumps(label, default=str), fixture_id))
    return len(label["gold_claims"])


if __name__ == "__main__":
    for fid in sys.argv[1:] or sorted(p.name for p in LABELS.iterdir() if p.is_dir()):
        print(fid, regold(fid), "gold claims")
