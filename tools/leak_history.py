"""The fixture answer-key leak, measured on the datasets themselves (postmortem 001).

For the v2 datasets (Phase 2) and the v3 datasets (Phase 2.5 onwards), counts log lines containing each
string the Phase 2 baseline's kind rules or the old injector relied on, by the fixture's scenario, and
the lines whose OpenTelemetry source attribute (`code.file.path`) is the fault module `faults.py`.

    uv run python tools/leak_history.py     # needs the v2 and v3 datasets under data/fixtures/
"""

import collections
import json
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = ["pool acquire timeout", "slow query", "provider charge failed", "deploy finished",
            "KeyError 'currency'", "connection pool resized"]  # fmt: skip


def main() -> None:
    for ver in ("v2", "v3"):
        by: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
        from_faults: collections.Counter[str] = collections.Counter()
        datasets = sorted(d for d in (ROOT / "data" / "fixtures").glob(f"*/{ver}") if (d / "label.json").exists())
        for d in datasets:
            scenario = json.loads((d / "label.json").read_text(encoding="utf-8"))["scenario"]
            for r in pq.read_table(d / "logs.parquet", columns=["body", "attrs"]).to_pylist():
                if "faults.py" in (dict(r["attrs"] or {}).get("code.file.path") or ""):
                    from_faults[scenario] += 1
                for p in PATTERNS:
                    if p.lower() in r["body"].lower():
                        by[p][scenario] += 1
        print(f"== {ver}: {len(datasets)} datasets; lines per scenario")
        for p in PATTERNS:
            print(f"  {p!r}: {dict(sorted(by[p].items()))}")
        print(f"  lines whose code.file.path is faults.py: {dict(sorted(from_faults.items()))}")


if __name__ == "__main__":
    main()
