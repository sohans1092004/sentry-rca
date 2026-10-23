# Sentry-RCA: How It Was Built

2026-10-23 · Sohan · companion: [interview guide](interview-guide.md) · live viewer: <https://sohans1092004.github.io/sentry-rca/>

**How to read this.** Every claim cites its source: a code line (a link such as `verifier.py:249`), a test name, a commit, a SPEC amendment (A1-A44 in `docs/SPEC.md`) or a measurement file. Every code link was checked by `docs/tools/refs.py check`; the result is at the end of section 11. Measurements say where they were made:

| Tag | Meaning |
|---|---|
| **[laptop]** | Measured on the development laptop: i7-12700H, 20 logical CPUs, 16 GB RAM, Intel Iris Xe (no NVIDIA GPU), Windows 11, Docker Desktop on WSL2 (`docs/measurements/phase1.md`) |
| **[hosted]** | Model output from `gemini-3.5-flash-lite` on the Gemini API free tier, called from the laptop; times include the network and the free tier's rate limits (A41) |
| **[replay]** | Re-run from recorded model responses (cassettes), no model called |
| **[CI]** | Measured in GitHub Actions |
| **[design]** | Designed and argued, not measured |

## 1. Overview

> **The deterministic baseline beat the LLM agent on held-out incidents. On 16 test incidents it scored top-1 0.438 against the agent's 0.250; paired incident by incident, the agent won 1, lost 4 and tied 11 [hosted]. The agent lost because it rarely managed to prove anything: it abstained on 8 of 11 incidents with a real cause, ran out of tool calls in 11 of 16, and never reported two competing causes.**

Sentry-RCA is an incident-investigation platform for a small demo system. Four instrumented services send metrics, logs and traces through Redpanda into ClickHouse. A rule-based alert opens an incident. An investigation then looks for the root cause with read-only, scope-checked tools. It can use a deterministic **baseline ranker**, an **LLM agent**, or both on the same incident.

Every cause either of them proposes is a **hypothesis made of typed claims** (a metric rose, a log pattern rose, a deploy preceded the onset, one service's spans dominate the slow traces). Each claim cites the exact rows it rests on. A **deterministic verifier** recomputes every claim from those rows before anything is shown. An unsupported claim never reaches a person, whatever a model was persuaded to say (`docs/SPEC.md` §8, ADR-007).

**What exists today**

| Part | What it is | Size and proof |
|---|---|---|
| Telemetry pipeline | 4 demo services plus a batch job, an OpenTelemetry Collector, Redpanda, 3 stream processors, ClickHouse | ingestion ceiling ~100,000 mixed events/s with bounded lag **[laptop]** (`docs/measurements/phase1.md`, M5) |
| Alerting | one composite SLO rule on the edge service: error rate, and p95 latency as a robust z-score (A1, A8) | alert 13.0-26.7 s after fault start on the 34 fast-onset v3 fixtures **[laptop]** (`docs/measurements/phase2_5.md`, Q1) |
| Failure injector and recorder | 10 fault scenarios plus no-fault; confounders; fixtures recorded as versioned Parquet datasets with labels | 35 fixtures: 19 dev, 16 held-out test (A22) |
| Investigation core | scope-checked tool layer, evidence snapshots, timeline, verifier, outcome rules | 189 unit and 33 integration tests |
| Baseline ranker | a fixed three-signal heuristic, no model (§7.2, ADR-006) | frozen as `baseline-frozen` before test was run (A32) |
| LLM agent | a hand-written tool loop (ADR-010) with record and replay, budgets and degradation to the baseline | frozen as `agent-frozen`, run once on test (A42, A43) |
| Evaluation | per-fixture paired comparison, dev and test apart, leak test, backend agreement, contamination rule | `docs/report-phase3.md` |
| Viewer | a static, read-only site of the recorded investigations | <https://sohans1092004.github.io/sentry-rca/> (A44) |
| Safety evidence | 69 remove-the-guard checks: each guard is deleted and its test must fail by showing the unsafe behaviour | `tools/guard_checks.out` |
| Records | 44 SPEC amendments, 10 ADRs, 4 postmortems, a measurement file per phase | `docs/` |

**The result, in one table** (one run per fixture, the free tier's limit; source `docs/report-phase3.md`):

| | dev agent | dev baseline | **test agent** | **test baseline** |
|---|---|---|---|---|
| top-1 judged | 0.316 | 0.842 | **0.250** | **0.438** |
| top-3 judged | 0.316 | 0.842 | 0.250 | 0.500 |
| outcome correct | 7/19 | 13/19 | 5/16 | 8/16 |
| paired by fixture (agent W/L/T) | 2/12/5 | | **1/4/11** | |

Under the rule registered before the test run (`docs/analysis-plan-phase3.md`), the agent **loses**: losses − wins = 3, and its mean is lower. The margin is exactly at the threshold. On dev, identical repeated runs changed their top answer in 4 of 6 pairs. So the size of the loss is not established; its direction is the same on dev, on test and at every iteration (section 8).

**What it deliberately does not do** (§1.3):
- **No remediation.** No tool can restart, roll back or change anything: the tool set has no write tool (`investigation/tools.py`).
- **No chatbot.** The agent runs only on an incident.
- **No cloud deployment.** It runs on one laptop; the public part is a static site.
- **No formal causal inference.** §7.2 states the heuristic used instead, and its blind spot.

**What was deferred in the final phase** (A44): the interactive UI and its API (verdicts, follow-ups, re-investigation), so human agreement has no data; observability dashboards; further chaos runs; resumable investigations; live end-to-end runs; the concurrent-investigations number. The fixture set meets every §12.1 minimum except injection fixtures: **3 of 5**.
