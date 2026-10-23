"""Per-run agent latency from what the model actually took: the sum of each recorded exchange's original
`latency_ms` (kept in the cassette and in llm_exchanges), plus the run's baseline time. An eval that
replays some exchanges from a cassette reports replay time as its wall time; this does not.

    uv run python tools/agent_latency.py runs/selection-qwen2.5_3b.json [...]
"""

import json
import statistics
import sys
from pathlib import Path

import psycopg

from common import config


def main(paths: list[str]) -> None:
    with psycopg.connect(config.PG_DSN) as conn:
        for p in paths:
            run_id = json.loads(Path(p).read_text())["eval_run_id"]
            rows = conn.execute(
                "SELECT r.fixture_id, i.budget_used, coalesce(sum((x.response->>'latency_ms')::int), 0), count(x.id) "
                "FROM eval_results r JOIN investigations i ON i.id = r.investigation_id "
                "LEFT JOIN llm_exchanges x ON x.investigation_id = i.id WHERE r.eval_run_id = %s "
                "GROUP BY r.fixture_id, i.budget_used ORDER BY r.fixture_id",
                (run_id,),
            ).fetchall()
            model_s = [m / 1000 for _, _, m, _ in rows]
            outcome_s = [(b.get("baseline_ms", 0) + m) / 1000 for _, b, m, _ in rows]
            print(json.dumps({"eval": p, "runs": len(rows),
                              "model_s": {"median": statistics.median(model_s), "mean": statistics.mean(model_s),
                                          "min": min(model_s), "max": max(model_s)},
                              "outcome_s_median": statistics.median(outcome_s),
                              "per_fixture_model_s": {f: round(m / 1000) for f, _, m, _ in rows}}))  # fmt: skip


if __name__ == "__main__":
    main(sys.argv[1:])
