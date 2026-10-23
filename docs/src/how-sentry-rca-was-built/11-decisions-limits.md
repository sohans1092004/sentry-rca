
## 11. Decisions, limits and what next

> **The design choices that mattered were about evidence: claims a machine can re-check, a scope the model cannot widen, and evaluation data that cannot leak. The limits are a small fixture set, one run per fixture for the agent, and a deferred product surface.**

### 11.1 Decisions (`docs/adr/`)

| ADR | Decision | Why, in one line |
|---|---|---|
| 000 | a provider interface; Ollama by default; the evaluated agent on a hosted free tier; record and replay | local 3B models verified nothing on CPU; no paid tier, zero cost |
| 001 | metrics, logs and traces in one ClickHouse store | one query language and one join surface: a metric step, its logs and its spans correlate in one place, and a fixture loads into one isolated database |
| 003 | Redpanda (Kafka API) for ingestion | a spike becomes lag, not loss; commit-after-insert plus stable IDs makes at-least-once harmless; one binary that fits a laptop |
| 004 | rule-based, statistical alerting | deterministic and explainable; the fixes were to measurement (A29, A30), not to a model |
| 006 | a causal-ranking heuristic, not causal inference | states its blind spots: no trace path (noisy_neighbor), trace dominance on ambiguous pairs |
| 007 | typed claims and a deterministic verifier | an LLM judge or a citation-exists check would accept what the rows do not show |
| 008 | scope from a server-side call-graph allowlist | the model's arguments are requests, never authority |
| 009 | no Redis | its jobs fit existing stores: a partial unique index for alert dedup, a unique trigger for exactly-once effect, advisory locks for the concurrency cap |
| 010 | a hand-written tool loop | about 200 lines, with every safety property visible and testable |
| 012 | content-addressed evidence snapshots | a claim is re-checked against exactly what the ranker saw |

### 11.2 Honest limits

- **The agent lost, and the size of the loss is not established.** It was measured at N=1 on 16 test fixtures, exactly at the decision threshold (section 8.4).
- **The fixture set is small and synthetic.** 35 fixtures from one 4-service demo system. Injection fixtures are 3 of the 5 §12.1 asks for (A44). The test split has 16 fixtures, because memory_leak_t01 never alerted.
- **Injection resistance is unmeasured.** Planted text seldom reached the agent, so the checks measured exposure (section 8.3).
- **The baseline's weights were set by hand**, and it is judged on the service only for four kinds it has no rule for (A23).
- **Model time breaks the 90 s target with the agent** (section 3).
- **A hosted model has no digest.** Replay reproduces the loop exactly; a live re-run may differ.
- **Not built** (A44): the interactive UI and API, observability dashboards, resumable investigations, live end-to-end runs, the concurrency number and the spike chaos run.
- **What killed the first test attempt** was not found (A43).

### 11.3 What next

The direction the data points to is recorded in ADR-000 as future work, not built: **the model re-ranks or explains the baseline's verified candidates instead of investigating from scratch**. It could not add a cause, so the verifier's guarantee and the outcome rules stay as they are. It would be measured the same way: frozen, pre-registered, test once, paired by fixture. Its ceiling is the baseline's candidate list (top-3 0.500 on test).

### 11.4 Reference check

Every code link in this document and the interview guide was produced by `docs/tools/refs.py build` from an anchor string, and re-checked by `check`. The check confirms that:
- each cited line still contains its anchor;
- each named file exists;
- each commit SHA exists;
- each backticked test name is defined under `tests/`.

Result at the time of writing:

```
$ uv run python docs/tools/refs.py check
checked 146 file references (79 line numbers), 2 commit SHAs, 15 test names
all references resolve
```
