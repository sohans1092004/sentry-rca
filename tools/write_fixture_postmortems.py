"""Write one postmortem per fixture into runbooks/postmortems/fixtures/, tagged with its fixture_id.

These contain the answer, which is the point: SPEC §12.2 excludes a fixture's own postmortem from
search_runbooks while that fixture is evaluated, and the contamination guard proves it.

    uv run python tools/write_fixture_postmortems.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "runbooks" / "postmortems" / "fixtures"

WHAT = {
    "bad_deploy": "a deploy of {svc} ({version}) introduced a regression in its request handler",
    "slow_query": "a database query in {svc} slowed down ({query}, about {delay} ms per call)",
    "pool_exhaustion": "{svc}'s database connection pool was exhausted (pool size {pool}); requests timed out "
    "waiting for a connection and payments retried them, multiplying the load",
    "dependency_outage": "the external payment provider failed or timed out for most calls from {svc}",
    "memory_leak": "an unbounded cache in {svc} grew without limit; memory rose and every request slowed",
    "noisy_neighbor": "a CPU-heavy batch job sharing a core with payments and inventory starved them of CPU",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for d in sorted((ROOT / "fixtures").iterdir()):
        label_path = d / "v1" / "label.json"
        if not label_path.exists():
            continue
        label = json.loads(label_path.read_text())
        inj = json.loads((d / "v1" / "injection.json").read_text())
        steps = {a["kind"]: a for a in inj["run"]["applied"]}
        rc = label["root_cause"]
        if rc is None:
            cause = (
                "there was no single cause: every service showed small random latency at once "
                "(background noise), and no deploy, error or dependency explained it"
            )
        else:
            a = next(iter(steps.values()))
            p = a["params"]
            cause = WHAT[rc["cause_kind"]].format(
                svc=rc["service"],
                version=p.get("version", ""),
                query=p.get("query", ""),
                delay=p.get("delay_ms", ""),
                pool=p.get("pool_size", ""),
            )
        alts = "; ".join(f"{x['service']} ({x['cause_kind']})" for x in label["acceptable_alternatives"])
        symptoms = ", ".join(label["symptom_services"]) or "none beyond the edge"
        body = (
            f"Incident on {inj['incident']['service']} opened {inj['incident']['opened_at']} "
            f"({inj['alert_latency_s']:.0f} s after the fault began).\n"
            f"Root cause: {cause}.\n"
            + (f"A second, overlapping cause was also present: {alts}.\n" if alts else "")
            + f"Symptoms: {symptoms} slowed or failed as a result.\n"
            f"Resolution: the fault was removed and the incident resolved on its own."
        )
        title = f"Postmortem: {label['scenario'].replace('_', ' ')} incident ({label['fixture_id']})"
        (OUT / f"{label['fixture_id']}.md").write_text(
            f"title: {title}\nkind: postmortem\nfixture_id: {label['fixture_id']}\n---\n{body}\n", encoding="utf-8"
        )
    print(len(list(OUT.glob("*.md"))), "fixture postmortems")


if __name__ == "__main__":
    main()
