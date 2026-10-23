
## 3. Requirements, point by point

> **The platform targets are met with the baseline. With the agent, the final outcome misses its 90 s target. One number was never measured, and human agreement has no data.**

### 3.1 Product requirements (§1.2)

| Requirement | Target | Result | Source |
|---|---|---|---|
| Ingestion throughput | 5,000 events/s sustained; report the ceiling | **met**: ~100,000 mixed events/s with bounded lag; lag grows without bound from 125,000. The bottleneck is the CPU of the single-threaded Python processors (metrics 99.6 %, logs 98.4 % of a core) **[laptop]** | `docs/measurements/phase1.md`, M5 |
| Alert-to-incident latency | < 30 s for fast-onset faults | **met**: 13.0-26.7 s on all 34 fast-onset v3 fixtures, measured from fault start to incident opened ([[record#summary["alert_latency_s"] = ]]), stricter than from anomaly onset. Slow-onset memory_leak_001: 164.4 s, no target (A12) **[laptop]** | `docs/measurements/phase2_5.md`, Q1 |
| First verified hypothesis | < 60 s, single service | **met**: always the baseline's, 1.3-3.5 s on test and dev evals (median 2.0 s and 2.5 s) **[laptop]** | `docs/measurements/phase2_5.md`, Q3 |
| Final outcome | < 90 s, single service | **met by the baseline** (as above). **Missed with the agent**: recorded model time per test investigation was 118 s median, 213 s max **[hosted]** | `docs/report-phase3.md` |
| Platform without the LLM | ingestion, alerting and baseline keep working | **met**: Ollama killed mid-investigation → `degraded_baseline` showing the baseline's verified answer, no rows lost **[laptop]**; the baseline needs no model (runbook vectors replay from a cassette, A17) | `docs/measurements/phase3/kill-ollama-demo.txt` |
| Hot retention | 7 days at full resolution | **built**: 7-day TTL on raw telemetry; an archive job exports each day at 6 days old (A5) **[design]**, not observed over a full week | A5 |
| Cold retention | 90 days: metrics 1 h, logs and traces to Parquet | **built**: hourly downsampling, deduplicated (A10); archives deleted after 90 days (A5) **[design]** | A5, A10 |
| Concurrent investigations | a measured number | **not measured** (A44). A cap of 2 exists ([[orch#MAX_CONCURRENT = 2]]) | A44 |
| Cost per investigation | tokens and wall time; money 0 with the local model | **met**: money 0 (local model, and the hosted free tier). Agent tokens per test run 102k median, 126k max **[hosted]** | `docs/report-phase3.md` |
| Memory | whole stack with the model ≤ 11 GB RSS | **met, measured in parts**: stack 2.07 GB (17 containers) **[laptop]**; qwen2.5:3b runner 2.2-2.4 GB with `OLLAMA_NUM_PARALLEL=1` **[laptop]**; the hosted agent uses no local model memory | `docs/measurements/phase2_5.md`, Q5; ADR-000 |

### 3.2 AI quality metrics (§1.4)

| Metric | Result | Source |
|---|---|---|
| Top-1, top-3, confusion matrix, agent vs baseline | all recorded, dev and test apart, at one run per fixture for the agent (section 8) | `docs/report-phase3.md` |
| Spread over N runs | baseline: 0 (deterministic, N=5). Agent: N=1 (the free tier allows 500 requests a day; N=5 needs about 3,200, A41). The measured stand-in: identical dev runs changed rank 1 in 4 of 6 pairs | `docs/measurements/phase3/iterations/iterC-day1.md` |
| Verifier rejection rate | agent: 2 of 6 hypotheses on test, 2 of 6 on dev; baseline 0 of 40 on test | `docs/report-phase3.md` |
| Verifier false-negative rate (must be 0) | **0**: 0 of 41 test and 0 of 54 dev gold claims rejected | `docs/measurements/phase2_5.md`, Q3 |
| Injection-influence rate | 0 of 6 pairs in a 3+3 dev check; 0 of 1 on test. But planted text reached the agent in only 1 of 6 dev runs and none on test, so this measures exposure more than resistance | `docs/measurements/phase3/iterations/iterC-day1.md` |
| Human agreement | **no data**: verdicts were deferred with the interactive UI (A44) | A44 |
| Budget use | tool calls, tokens and model time per run, recorded per investigation | `docs/report-phase3.md` |
