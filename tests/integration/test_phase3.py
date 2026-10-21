"""Phase 3 against real Postgres: the orchestrator runs the baseline, then the agent; an LLM failure or
unusable output ends degraded_baseline with the verified baseline answer shown and every committed row
kept (tool calls, LLM exchanges, baseline hypotheses). The model is scripted; the database is real."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from common.config import DEMO_TENANT_ID
from investigation import llm, orchestrator
from investigation.agent import AgentConfig
from investigation.backend import OfflineBackend
from investigation.scope import iso
from tests.integration.test_phase2 import app_conn

T0 = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
FAULT = T0 + timedelta(minutes=20)
POOL = "QueuePool limit of size 10 overflow 0 reached, connection timed out, timeout 0.50"
LOGS = {"service": "inventory", "start": iso(FAULT - timedelta(minutes=2)), "end": iso(FAULT + timedelta(minutes=2))}


def backend():
    logs = [{"tenant_id": DEMO_TENANT_ID, "service": "inventory", "ts": FAULT + timedelta(seconds=10 * i),
             "severity": "WARN", "body": POOL, "trace_id": "", "span_id": "", "attrs": {}, "log_id": f"l{i}"}
            for i in range(10)]  # fmt: skip
    return OfflineBackend({"metrics": [], "spans": [], "logs": logs, "deploys": []})


def claim():
    return {"type": "log_pattern", "service": "inventory", "window": [iso(FAULT), LOGS["end"]],
            "pattern": "queuepool limit", "min_count": 5, "min_ratio": 2.0}  # fmt: skip


def fixed_ranker(scope, call, runbook_search=False):
    """Stands in for the baseline: one query, one verifiable root cause."""
    rec = call("query_logs", LOGS)
    return [{"rank": 1, "causal_role": "candidate_root_cause", "cause_service": "inventory",
             "cause_kind": "pool_exhaustion", "score": 0.7,
             "claims": [{**claim(), "cites": [{"tool_call_seq": rec.seq,
                                               "row_ids": [r["row_id"] for r in rec.rows]}]}]}]  # fmt: skip


class Script:
    name, model, digest = "script", "script-model", "0"

    def __init__(self, steps):
        self.steps = list(steps)

    def complete(self, messages, tools, temperature=0.0, schema=None, timeout_s=None):
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def config(steps):
    return AgentConfig(lambda sink: llm.Recorded(None, 0, "live", Script(steps), sink=sink))


def start(pg, pg_dsn, trigger="t"):
    iid = str(uuid.uuid4())
    pg.execute("INSERT INTO incidents (id, tenant_id, fingerprint, service, status, first_anomaly_at, last_seen) "
               "VALUES (%s, %s, %s, 'inventory', 'open', %s, %s)",
               (iid, DEMO_TENANT_ID, f"test:{iid}", FAULT, FAULT + timedelta(minutes=2)))  # fmt: skip
    app = app_conn(pg_dsn)
    inv, _ = orchestrator.trigger(app, {"incident_id": iid, "trigger_id": trigger})
    return app, inv


def investigate(app, inv, agent):
    return orchestrator.investigate(app, backend(), None, inv, clamp=(T0, T0 + timedelta(minutes=30)),
                                    rank=fixed_ranker, agent=agent)  # fmt: skip


def counts(pg, inv):
    q = "SELECT count(*) FROM {} WHERE investigation_id = %s"
    return {t: pg.execute(q.format(t), (inv,)).fetchone()[0] for t in ("tool_calls", "llm_exchanges", "hypotheses")}


def test_an_llm_failure_mid_investigation_degrades_to_the_verified_baseline(pg, pg_dsn):
    """§7.1 step 5, §15 row 7: the model answers one turn, then becomes unreachable (Ollama killed)."""
    app, inv = start(pg, pg_dsn)
    agent = config([llm.Response("", [{"name": "query_logs", "arguments": LOGS}], 50, 5),
                    llm.Unavailable("connection refused (3 attempts)")])  # fmt: skip
    try:
        investigate(app, inv, agent)
    except Exception as e:  # noqa: BLE001 -- the assertion below says what the investigation was left as
        print(f"investigate raised {type(e).__name__}: {e}")
    status, outcome, ranker, budget = pg.execute(
        "SELECT status, outcome, ranker, budget_used FROM investigations WHERE id = %s", (inv,)).fetchone()  # fmt: skip
    assert (status, ranker) == ("degraded_baseline", "baseline"), f"left as {status!r}, showing {ranker!r}"
    assert outcome == "ROOT_CAUSE_IDENTIFIED" and budget["degraded"] == "llm_unavailable"
    shown = pg.execute("SELECT cause_service, verifier_status FROM hypotheses WHERE investigation_id = %s "
                       "AND ranker = 'baseline'", (inv,)).fetchall()  # fmt: skip
    assert shown == [("inventory", "passed")]
    # nothing committed before the failure is lost: the baseline's call, the agent's call, its exchange
    assert counts(pg, inv) == {"tool_calls": 2, "llm_exchanges": 1, "hypotheses": 1}
    rankers = pg.execute("SELECT ranker FROM tool_calls WHERE investigation_id = %s ORDER BY seq", (inv,)).fetchall()
    assert rankers == [("baseline",), ("agent",)]


def test_malformed_output_gets_one_retry_then_degrades(pg, pg_dsn):
    """§15 row 8."""
    app, inv = start(pg, pg_dsn)
    investigate(app, inv, config([llm.Response("the pool, probably"), llm.Response('{"hypotheses": "pool"}')]))
    status, budget = pg.execute("SELECT status, budget_used FROM investigations WHERE id = %s", (inv,)).fetchone()
    assert status == "degraded_baseline" and budget["degraded"] == "parse"
    assert budget["agent"]["parse_failures"] == 2
    second = pg.execute("SELECT request FROM llm_exchanges WHERE investigation_id = %s AND seq = 2", (inv,)).fetchone()
    assert second[0]["messages"][-1]["content"].startswith("Your reply could not be used:")


def test_a_completed_agent_is_shown_and_both_rankers_are_kept(pg, pg_dsn):
    app, inv = start(pg, pg_dsn)
    final = {"hypotheses": [{"rank": 1, "causal_role": "candidate_root_cause", "cause_service": "inventory",
                             "cause_kind": "pool_exhaustion", "score": 0.9, "narrative": "pool timeouts",
                             "claims": [{**claim(), "cites": [{"tool_call_seq": 1, "rows": "all"}]}]}]}  # fmt: skip
    outcome = investigate(app, inv, config([llm.Response("", [{"name": "query_logs", "arguments": LOGS}], 50, 5),
                                            llm.Response(json.dumps(final), [], 80, 40)]))  # fmt: skip
    status, ranker, budget = pg.execute(
        "SELECT status, ranker, budget_used FROM investigations WHERE id = %s", (inv,)).fetchone()  # fmt: skip
    assert (outcome, status, ranker) == ("ROOT_CAUSE_IDENTIFIED", "complete", "agent")
    assert budget["agent"]["llm_calls"] == 2 and budget["agent"]["tokens_in"] == 130
    results = pg.execute("SELECT ranker, outcome FROM investigation_results WHERE investigation_id = %s ORDER BY 1",
                         (inv,)).fetchall()  # fmt: skip
    assert results == [("agent", "ROOT_CAUSE_IDENTIFIED"), ("baseline", "ROOT_CAUSE_IDENTIFIED")]
    rows = pg.execute("SELECT seq, provider, model, request_hash, tokens_in FROM llm_exchanges "
                      "WHERE investigation_id = %s ORDER BY seq", (inv,)).fetchall()  # fmt: skip
    assert [(s, p, m, t) for s, p, m, _, t in rows] == [(1, "script", "script-model", 50),
                                                         (2, "script", "script-model", 80)]  # fmt: skip
    assert all(len(h) == 64 for _, _, _, h, _ in rows)
