"""The baseline's outcome on each fixture of one split, offline (Parquet backend, no runbooks): a quick
look while developing, never a substitute for `rca eval`. Refuses the test split while the baseline is
not frozen, so test results cannot leak into baseline development (A27).

    uv run python tools/offline_outcomes.py [dev|test]
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common.config import DEMO_TENANT_ID
from investigation import scope as scope_mod
from investigation.backend import OfflineBackend
from investigation.run import run_ranker
from investigation.tools import MemoryStore
from recorder.dataset import TABLES, read_parquet

ROOT = Path(__file__).resolve().parent.parent


def main(split: str) -> None:
    tags = subprocess.run(["git", "tag", "--points-at", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout
    if split == "test" and "baseline-frozen" not in tags.split():
        sys.exit("refused: the test split is looked at only with the frozen baseline (A27)")
    index = json.loads((ROOT / "fixtures" / "index.json").read_text())
    for a in index["fixtures"]:
        d = ROOT / "data" / "fixtures" / a["fixture_id"] / a["version"]
        label = json.loads((d / "label.json").read_text())
        if label.get("split", "dev") != split:
            continue
        inc = json.loads((d / "injection.json").read_text())["incident"]
        window = [datetime.fromisoformat(t) for t in json.loads((d / "manifest.json").read_text())["window"]]
        backend = OfflineBackend({t: read_parquet(d / f"{t}.parquet") for t in TABLES})
        incident = {"tenant_id": DEMO_TENANT_ID, "service": inc["service"],
                    "first_anomaly_at": datetime.fromisoformat(inc["first_anomaly_at"]),
                    "last_seen": datetime.fromisoformat(inc["last_seen"])}  # fmt: skip
        sc = scope_mod.compute(backend, incident, clamp=(window[0], window[1]), excluded_fixture=a["fixture_id"])
        r = run_ranker(MemoryStore(), backend, None, "inv", sc)
        roots = [(h["cause_service"], h["cause_kind"], h["score"]) for h in r.verified
                 if h["causal_role"] == "candidate_root_cause"]  # fmt: skip
        rejected = [(h["cause_service"], h["cause_kind"], v.reason) for h, v in zip(r.hypotheses, r.verification,
                                                                            strict=True) if not v.passed]  # fmt: skip
        want = label["root_cause"] and (label["root_cause"]["service"], label["root_cause"]["cause_kind"])
        print(json.dumps({"fixture": a["fixture_id"], "expected": label["expected_outcome"], "label": want,
                          "outcome": r.outcome, "roots": roots[:3], "rejected": rejected,
                          "confounded": bool(label.get("confounders"))}), flush=True)  # fmt: skip


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dev")
