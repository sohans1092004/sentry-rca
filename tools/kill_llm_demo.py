"""Phase 3 failure demonstration (§15 row 7): kill Ollama in the middle of a live agent investigation and
show it ends `degraded_baseline` with the verified baseline answer and no lost rows.

Runs `rca eval --ranker agent` (local model, record mode) on one DEV fixture, waits until the agent has
two committed LLM exchanges, kills the Ollama processes, lets the eval finish, prints what the
investigation was left with, then restarts Ollama.

    uv run python tools/kill_llm_demo.py [fixture=pool_exhaustion_001] [model=qwen2.5:3b]
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg

from common import config

ROOT = Path(__file__).resolve().parent.parent
OLLAMA = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Ollama" / "ollama.exe"


def main(fixture: str, model: str) -> None:
    conn = psycopg.connect(config.PG_DSN, autocommit=True)
    t0 = time.time()
    out = ROOT / "runs" / "kill-llm-demo.json"
    eval_ = subprocess.Popen(["uv", "run", "rca", "eval", "--ranker", "agent", "--model", model, "--llm", "record",
                              "--split", "dev", "--n", "1", "--wall-s", "600", "--tag", "killdemo", "--out", str(out),
                              fixture], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
    inv = None
    while eval_.poll() is None:
        row = conn.execute(
            "SELECT i.id::text, (SELECT count(*) FROM llm_exchanges x WHERE x.investigation_id = i.id) FROM "
            "investigations i WHERE i.started_at > to_timestamp(%s) AND i.budget_used = '{}' "
            "ORDER BY i.started_at DESC LIMIT 1", (t0,)).fetchone()  # fmt: skip
        if row and row[1] >= 2:
            inv = row[0]
            break
        time.sleep(1)
    assert inv, "the agent never reached two exchanges"
    killed_at = time.time()
    for image in ("llama-server.exe", "ollama.exe", "ollama app.exe"):
        subprocess.run(["taskkill", "/IM", image, "/F"], capture_output=True)
    print(f"killed Ollama {killed_at - t0:.0f} s into the eval, after 2 committed exchanges of {inv}")
    eval_.wait()
    status, ranker, outcome, budget = conn.execute(
        "SELECT status, ranker, outcome, budget_used FROM investigations WHERE id = %s", (inv,)).fetchone()  # fmt: skip
    counts = {t: conn.execute(f"SELECT count(*) FROM {t} WHERE investigation_id = %s", (inv,)).fetchone()[0]
              for t in ("tool_calls", "llm_exchanges", "hypotheses")}  # fmt: skip
    by_ranker = conn.execute("SELECT ranker, count(*) FROM tool_calls WHERE investigation_id = %s GROUP BY 1",
                             (inv,)).fetchall()  # fmt: skip
    shown = conn.execute("SELECT cause_service, cause_kind, verifier_status FROM hypotheses "
                         "WHERE investigation_id = %s AND ranker = 'baseline' ORDER BY rank",
                         (inv,)).fetchall()  # fmt: skip
    print(json.dumps({"investigation": inv, "status": status, "shown_ranker": ranker, "outcome": outcome,
                      "degraded": budget.get("degraded"), "detail": budget.get("degraded_detail"),
                      "rows": counts, "tool_calls_by_ranker": dict(by_ranker),
                      "baseline_hypotheses": shown, "agent": budget.get("agent", {}).get("llm_calls")},
                     indent=1, default=str))  # fmt: skip
    subprocess.Popen([str(OLLAMA), "serve"], env={**os.environ, "OLLAMA_NUM_PARALLEL": "1"},
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))  # fmt: skip
    print("Ollama restarted")


if __name__ == "__main__":
    main(*(sys.argv[1:3] or ["pool_exhaustion_001", "qwen2.5:3b"]))
