# Sentry-RCA: Interview Guide

Private prep · 2026-10-23 · companion: [how Sentry-RCA was built](how-sentry-rca-was-built.md) · viewer: <https://sohans1092004.github.io/sentry-rca/>

**How to use this.**
1. Learn the pitches (section 1) and the headline numbers (section 6).
2. Work through the question bank out loud (section 3).
3. Every answer points at the code or the record it relies on. Open the link and read the lines before you trust the answer.

Measurements carry the same tags as the main document: **[laptop]**, **[hosted]** (the Gemini free tier, called from the laptop), **[replay]**, **[CI]** and **[design]**. Every code link was checked by `docs/tools/refs.py check`.

## 1. Pitches

> **The same story at three lengths: what it does, the result, why the result is believable, and what it does not do.**

### 30 seconds

"Sentry-RCA investigates production incidents. It has a telemetry pipeline into ClickHouse, an alert that opens incidents, and an investigation that proposes root causes, either from a deterministic heuristic or from an LLM agent with read-only, scoped tools.

Every proposed cause is a set of typed claims citing exact rows, and a deterministic verifier recomputes each claim before anyone sees it. So a model can be wrong, but it can't make an unsupported claim reach a person.

I compared the two on 16 held-out incidents with a pre-registered plan. The baseline won: 0.438 top-1 against 0.250, and paired incident by incident the agent won 1, lost 4 and tied 11. The agent was safe but mostly said 'insufficient evidence'."

### 2 minutes

1. **The problem.** When an alert fires, someone has to find which service caused it. A model can read telemetry fast, but it can also invent a cause, or be steered by text inside a log line.
2. **The guardrails are outside the model.**
   - The server decides the scope: tenant, services within 2 call-graph hops, the time window.
   - Every tool result is stored as a content-addressed snapshot.
   - The model's answer must be strict JSON: hypotheses made of typed claims (a metric rose, a log pattern at least doubled, one service's spans dominate the slow traces, a deploy preceded the onset).
   - The verifier recomputes each claim from the cited rows. The outcome rules use only verified hypotheses.
3. **The baseline runs first, always**, so a verified answer exists before any model is called. If the model fails, the investigation degrades to it.
4. **Evaluation discipline.**
   - My first eval scored 1.00, because the fault injector's own log lines named the fault. I rebuilt the faults to surface only through normal code paths, added confounders and a held-out test split, and wrote a leak test.
   - The baseline dropped to 0.842 on dev and 0.438 on test.
   - Then the agent: model chosen on dev, prompt iterated on dev, analysis plan committed, tag frozen, test run once.
5. **The result.** The agent lost. It abstained on 8 of 11 incidents with a real cause, ran out of tool calls in 11 of 16, and never proposed two competing causes. The verifier rejected none of the gold claims and let nothing out of scope through.
6. **Honest limits.** One run per fixture, because the free tier allows 500 requests a day. 16 test fixtures. The loss sits exactly on the decision threshold.

### 10 minutes: script, and what to draw

| Minute | Say | Draw |
|---|---|---|
| 0-1 | The promise: no unsupported claim reaches a person. What it does not do: no remediation, no chatbot | nothing yet |
| 1-3 | The pipeline and the alert; why one edge alert (A1) | **box diagram** (drill 5.1) |
| 3-5 | One investigation: scope, baseline first, tool calls with snapshots, hypotheses, verifier, outcome rules | **sequence** (drill 5.2) |
| 5-6 | A claim, and how the verifier recomputes it; why not an LLM judge | **a `log_pattern` claim with its two windows** (drill 5.3) |
| 6-8 | The leak story: 1.00 → 0.842 / 0.438; the leak test; frozen baseline; held-out split | the v2 vs v3 string table |
| 8-9 | The agent: the data boundary, budget, record and replay; the result, paired by fixture | the paired W/L/T line |
| 9-10 | Why it lost, and what I'd build next: the model re-ranking the baseline's verified candidates | point at the verifier: it stays |
