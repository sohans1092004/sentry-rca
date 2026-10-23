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


## 2. How it was built, honestly

> **Spec-driven and AI-assisted: I owned the specification and every decision at its gaps; Claude Code wrote the code under fixed ground rules; the evidence is in the amendments, the guard checks and the measurements.**

**What to say, plainly:**
- "I owned the specification, `docs/SPEC.md`. It changed through 44 dated amendments, each landed with the code it governs and its reason." The repo does not record how the spec itself was drafted. If AI helped draft it too, say so in the same breath.
- "The code was written by an AI coding agent under ground rules I set:
  - stop and ask at every gap or contradiction;
  - never invent a number;
  - never weaken a test;
  - prove every safety guard by removing it and watching its test fail;
  - keep dev and test apart;
  - zero cost."
- "The decisions at the gaps were mine. Examples:
  - the replay-key placeholder (A35);
  - the cause-link verifier rule (A36);
  - a final answer turn before degrading (A37);
  - moving the evaluated agent to a hosted free tier (A41);
  - freezing iteration C for budget compliance rather than accuracy (A42);
  - completing the interrupted test run from its recordings (A43);
  - trimming Phase 4 (A44)."
- "The problems found along the way are on the record, with their fixes:
  - the 1.00 that was too good (postmortem 001);
  - a model-selection misread, corrected in ADR-000;
  - the agent citing the baseline's calls (postmortem 004)."

**If asked "what did you write yourself?"** Answer from the record, and claim no more than it shows. Yours: the spec, the ground rules, and the decisions at the gaps listed above. Written by the agent under your review: the code, the analysis plan and these documents. Then offer to walk through any part of the code, and do it from the links in this guide.

**If asked "would you trust the agent's result more if it had won?"** No. The frozen-plan discipline exists so that the answer doesn't depend on which way it came out. The same rule that called this a loss would have called a 3-fixture margin the other way a win, and I'd have reported the same caveat about N=1.


## 3. Question bank

> **Each answer gives the claim, the mechanism, and where to point.**

### 3.1 The result

**Q: Did the LLM help?**
Not on this evidence.
- On 16 held-out incidents the baseline scored top-1 0.438 against the agent's 0.250 **[hosted]**.
- Paired by fixture, the agent had 1 win, 4 losses and 11 ties. That is a loss under the pre-registered rule: losses − wins ≥ 3, with a lower mean (`docs/analysis-plan-phase3.md`).
- On dev it lost too (2/12/5).

**Q: Is that significant?**
Don't claim it is.
- At N=1 the sign test gives p = 0.375 on test. It is reported as description only.
- The decision rule was set before the run, and it lands exactly at its threshold.
- Identical dev runs changed rank 1 in 4 of 6 pairs, so the size of the loss is not established.
- What is established: the direction is the same on dev, on test and at every iteration.

**Q: Why did it lose?**
From the data (`docs/report-phase3.md`):
- it abstained on 8 of 11 root-cause fixtures;
- 11 of 16 runs used all 20 tool calls;
- it never proposed two competing causes, so it scored 0 of 6 on CONFLICTING;
- it scored 0.111 on confounded fixtures.

The verifier rejected 2 of its 6 test hypotheses. One was the right cause with an under-covered log query (pool_exhaustion_t01).

**Q: Then why is the agent there at all?**
- It is the measured alternative.
- The safety design is the reusable part: a scope the model can't widen, data framed as untrusted, strict output, a hard budget, degradation to a verified baseline, and a verifier that decides.
- What I'd build next uses the model where the data says it might help: re-ranking or explaining the baseline's verified candidates (ADR-000, future work).

**Q: Why didn't you just use a bigger model?**
- **Zero cost was a rule.** The laptop has 16 GB and no NVIDIA GPU, and qwen2.5:7b did not fit beside the stack (ADR-000).
- **The local 3B models verified 0 of 145 hypotheses.**
- **Paid tier: declined.** No paid tier was allowed, and using several free accounts to raise the quota would break the provider's terms.
- So the honest scope is "a free-tier flash model at N=1".

### 3.2 The verifier and claims

**Q: Why typed claims and a deterministic verifier, not an LLM judge?**
- **A judge is another model**, one a planted line can also persuade, and its errors are hard to test.
- **A claim is recomputable.** "Inventory's pool-wait mean rose at least 4x over the 15 minutes before" can be recomputed from the cited rows, the same way every time ([`verifier.py:101`](../investigation/verifier.py#L101)).
- **"The citation exists" is not enough.** A row can exist and show nothing (ADR-007).

**Q: What does a `log_pattern` claim have to prove?**
- At least `min_count` cited lines contain the pattern.
- The cited queries cover the window *and* the equal-length window before it, untruncated.
- Matches in the window ÷ matches before is at least 2 ([`verifier.py:123`](../investigation/verifier.py#L123), A24).

Presence alone proves nothing, because healthy traffic logs the same vocabulary (A21).

**Q: Can the agent cite the baseline's evidence?**
No.
- Every citation must be a tool call of the same ranker ([`verifier.py:74`](../investigation/verifier.py#L74), A15). `test_a_hypothesis_citing_the_baseline_rankers_call_is_rejected`; guard `same_ranker_citations`.
- Postmortem 004: the agent did cite baseline call numbers by mistake, and every such claim was rejected.

**Q: Can true evidence verify a false cause?**
It could, until A36. Now a root cause must be in scope, and at least one non-runbook claim must be about that service ([`verifier.py:249`](../investigation/verifier.py#L249)). Otherwise honest evidence about inventory could have verified a hypothesis naming `dns`.

**Q: What can the verifier not stop?**
A hypothesis whose claims are all true of the data but whose conclusion is wrong. no_fault_002 is the example: the agent's payments / dependency_outage was verified on a fixture with no fault, because provider failures and latency really did rise at an onset. It's a showcase in the viewer. The verifier guarantees support, not truth.

### 3.3 Scope, security and injection

**Q: How do you stop prompt injection?**
In layers, none of them the prompt alone:
1. **Untrusted text is framed as data.** It appears only inside a data block whose boundary is random for each call ([`agent.py:183`](../investigation/agent.py#L183)). `test_planted_instructions_only_ever_appear_inside_a_data_block`.
2. **The model cannot widen its reach.** The server-side scope rejects any other tenant or service ([`tools.py:95`](../investigation/tools.py#L95)).
3. **The output must parse**, with a closed list of kinds.
4. **The verifier rejects a cause with no evidence about it.**

The obedient-fake-model tests show each layer stopping its attack (`tests/unit/test_agent.py`). Delimiting is a mitigation, not a guarantee, and §11 says so.

**Q: What was the injection-influence rate?**
- 0 of 6 pairs in a 3+3 dev check, and 0 of 1 on test.
- But planted text reached the agent in only 1 of 6 dev runs and none on test. So this measures exposure, not resistance.
- In all 5 hosted dev runs where planted text was seen, the planted cause was never named.

**Q: The viewer shows attacker-controlled log lines. How is that safe?**
- **Everything renders as text.** Every data value goes through `createTextNode` or an attribute value ([`app.js:8`](../viewer/app.js#L8)).
- **A strict CSP** blocks inline script.
- **A headless-Chromium test** plants payloads in every field and asserts that nothing executes and nothing becomes markup ([`test_viewer_xss.py:128`](../tests/viewer/test_viewer_xss.py#L128)).
- **Two guards:** with text rendering replaced by HTML parsing the test reports injected elements, and with the CSP removed an inline script runs.

**Q: Where did the API key live?**
- Only in a user environment variable, sent only in an HTTP header.
- A secret scan covers the repository, every cassette and the published viewer ([`secret_scan.py:34`](../tools/secret_scan.py#L34), guard `secret_scan`).
- The key was revoked after the test run.

### 3.4 Evaluation

**Q: Your first baseline scored 1.00. What happened?**
The fixtures leaked the answer (postmortem 001):
- fault-only log strings such as `pool acquire timeout` (198 lines, only in pool_exhaustion fixtures);
- a `code.file.path` of `faults.py` on 325 injected lines;
- later, an HTTP span from starting the batch job.

Faults now surface only through normal code paths, healthy traffic speaks the same words, and a leak test finds markers by measurement. The baseline fell to 0.842 dev and 0.438 test.

**Q: How do you know the test set is held out?**
- **Built apart.** It was recorded separately, with four scenarios the baseline has no rules for (A22).
- **The baseline was frozen first.** It was frozen with its sha256 before test was first evaluated, and any later change blocks the gate until a post-hoc amendment (A27).
- **The agent can't run on test unfrozen.** The CLI refuses a live agent run on test fixtures unless HEAD has the `agent-frozen` tag ([`cli.py:128`](../investigation/cli.py#L128)).
- **No postmortems.** Test fixtures have none in the corpus (A25).

**Q: Why paired by fixture rather than comparing means?**
- Both rankers ran in the same investigation of the same fixture, so per-fixture differences remove fixture difficulty.
- With 16 fixtures, counting wins and losses is honest about how little data there is ([`harness.py:469`](../evals/harness.py#L469)).

**Q: Why N=1?**
- The free tier allows 500 requests a day, and N=5 over dev and test needs about 3,200 (A41).
- The noise was measured instead: 3 runs with and 3 without planted lines on two dev fixtures.

**Q: The test run was interrupted. Doesn't that taint it?**
- It is recorded as a deviation (A43).
- It was completed at the same commit with the same command.
- The 13 finished fixtures replayed from their recorded responses, so there was no second draw, and were checked identical to the first attempt.
- Only the 3 unfinished fixtures called the model.

**Q: How do you know ClickHouse isn't skewing results?**
- Every tool call of every eval is re-run on a Parquet backend, and the snapshot must be byte-identical (A26).
- It caught one real difference, from approximate `uniq` (A33).

### 3.5 The agent loop

**Q: Why no agent framework?**
- The loop is about 200 lines, where every safety property is visible: budget checks, boundary framing, strict parsing, the repair turn and degradation ([`agent.py:474`](../investigation/agent.py#L474), ADR-010).
- A framework would hide the control flow I needed to test with fake models.

**Q: What happens when the budget runs out?**
- One last turn with no tools, in which the model must answer.
- If it asks for tools again, or the token or wall-time budget is used, the investigation degrades to the baseline (A37).
- `test_the_tool_call_budget_stops_a_looping_agent`.

**Q: How is it reproducible in CI without a model?**
- Record and replay. The key covers the whole canonical request with each random boundary replaced by a placeholder ([`llm.py:81`](../investigation/llm.py#L81), A35).
- A miss raises, and never calls a model.
- CI's `agent-replay` job replays all 35 fixtures.

### 3.6 Pipeline and alerting

**Q: Exactly-once?**
- No: at-least-once, made harmless. Processors commit offsets after the ClickHouse insert, and stable row IDs plus ReplacingMergeTree collapse the redelivered copies.
- Guards: `commit_after_insert` and `stable_ids`.

**Q: What's the throughput ceiling and the bottleneck?**
- About 100,000 mixed events/s with bounded lag **[laptop]**.
- The CPU of the single-threaded Python processors is the limit: metrics at 99.6 % of a core at 125k.
- More partitions and one processor per partition is the upgrade path (`docs/measurements/phase1.md`, M5).

**Q: Why one alert rule on the gateway?**
- Per-service rules open 3-4 incidents per multi-hop fault, with no grouping (A1).
- One edge SLO rule opens one incident, and finding the cause is the investigation's job.

**Q: A fault didn't alert in testing. Why?**
The previous fault was inside the 30-minute alert baseline (postmortem 002, A29). Incident periods are now excluded, and the recorder waits for a clean baseline.

### 3.7 Why not X?

| Instead of | Why not | Where |
|---|---|---|
| an LLM judge | a model can be persuaded; claims can be recomputed | ADR-007 |
| letting the model pick services | the scope is server-side authority | ADR-008 |
| live re-queries for verification | data changes; snapshots are what the ranker saw | ADR-012 |
| ML anomaly detection | determinism and explainability; the alert fixes were to measurement | ADR-004 |
| formal causal inference | not with this data; the heuristic states its blind spots | ADR-006 |
| Redis | its jobs fit Postgres and process memory | ADR-009 |
| React for the viewer | three read-only pages; text nodes plus a browser test enforce the property | A44 |


## 4. Story bank

> **Each story: the situation, what I saw, what I did, the evidence it worked, what I learned.**

**The 1.00 that was too good** (postmortem 001)
- **Situation:** the first baseline eval scored top-1 1.00.
- **What I saw:** the kind rules matched strings that only the injector produced.
- **What I did:** rebuilt the faults to surface through normal code paths, gave healthy traffic the same vocabulary, made log claims prove a rise, added confounders and a held-out test split, and wrote a leak test.
- **The evidence:** the leak test then caught a third leak no one had looked for, the HTTP span from starting the batch job. After the fixes: 0 leaks over 18,340 items; baseline 0.842 dev, 0.438 test.
- **Lesson:** distrust a perfect score, and find markers by measurement, not by reading code.

**The fault that hid the next fault** (postmortem 002)
- **Situation:** two smoke-run faults raised p95 4x and did not alert.
- **What I saw:** the 30-minute baseline still held the previous fault, so its median was 179-224 ms instead of ~100.
- **What I did:** excluded incident periods from the baseline, and made the recorder wait for a clean one, including for a fault that never opened an incident.
- **Lesson:** two windows chosen separately must be checked together.

**The replay key that could never match** (postmortem 003)
- **Situation:** the spec asked for random per-call boundaries *and* a hash of the canonical request.
- **What I saw:** they contradict each other; no replay would ever hit.
- **What I did:** raised it before writing the recorder, and hashed with a placeholder for the boundary.
- **Lesson:** read the security section and the reproducibility section together.

**The agent that cited the baseline** (postmortem 004)
- **Situation:** dev selection: 0 of 48 agent hypotheses verified.
- **What I saw:** the agent cited low call numbers that belonged to the baseline, and the same-ranker check rejected them.
- **What I did:** local numbering for the agent, with the check unchanged.
- **Lesson:** a safety check that works can hide a usability bug. Read the rejection reasons, not only the rate.

**Losing on test, and saying so**
- **Situation:** the frozen agent lost under the rule I had registered before the run.
- **What I did:** reported it plainly, with the reasons from the data and the noise caveat. I didn't run another version on test, and didn't change the rule.
- **Lesson:** pre-registration makes the result mean something either way.

**The interrupted test run** (A43)
- **Situation:** the one test run was killed from outside after 13 of 16 fixtures.
- **What I did:** completed it at the same commit with the same command. The finished fixtures replayed from the recordings and were checked identical; only the 3 unfinished fixtures called the model. It is recorded as a deviation.
- **Lesson:** recordings turn "run it once" into something you can finish without drawing twice.

## 5. Whiteboard drills

### 5.1 The architecture in 2 minutes

Draw left to right:
1. the demo services;
2. Collector → Redpanda → processors → ClickHouse;
3. the alert engine → Postgres incident;
4. the orchestrator, with the tool layer (scope, caps, snapshot) beside it;
5. two rankers into one verifier;
6. the outcome.

Mark the trust boundary at the tool layer, and the model as a dependency behind record and replay.

### 5.2 One investigation

`incidents.opened` → compute scope → baseline: timeline, follow-up queries, traces → hypotheses → verify → store with outcome → agent: context, tool loop with framed results → JSON → resolve citations → verify → repair once if rejected → store → show the agent's result, or the baseline's if the agent degraded.

### 5.3 A log_pattern claim

Draw a time axis:
- the onset;
- the claim window W, from onset to onset + 2 min;
- the equal-length window P just before it;
- the query's span covering both.

The verifier counts matching lines in W and in P from the cited snapshot. It needs W ÷ max(P, 1) ≥ 2, and at least `min_count` cited lines in W. Show why "the line exists" fails when healthy traffic logs it too.

### 5.4 The paired comparison

A 16-row table: fixture, agent right?, baseline right?, verdict. Count W/L/T. Apply the rule: wins − losses ≥ 3 and a higher mean → beats; the mirror → loses; else no measurable difference. Then say why the sign test is only description at this N.


## 6. Numbers cheat sheet

| Number | Value | Tag and source |
|---|---|---|
| Test top-1 judged, agent vs baseline | 0.250 vs 0.438 | [hosted] `docs/report-phase3.md` |
| Test paired top-1, agent W/L/T | 1 / 4 / 11 | [hosted] same |
| Dev top-1 judged, agent vs baseline | 0.316 vs 0.842 | [hosted] same |
| Dev paired, agent W/L/T | 2 / 12 / 5 | [hosted] same |
| Test top-3, agent vs baseline | 0.250 vs 0.500 | [hosted] same |
| Agent abstentions on root-cause test fixtures | 8 of 11 | [hosted] same |
| Runs using all 20 tool calls (test) | 11 of 16 | [hosted] same |
| Identical dev runs changing rank 1 | 4 of 6 pairs | [hosted] `docs/measurements/phase3/iterations/iterC-day1.md` |
| Agent hypotheses verified (test) | 4 of 6 | [hosted] `docs/report-phase3.md` |
| Gold claims rejected (verifier false negatives) | 0 of 54 dev, 0 of 41 test | [laptop] `docs/measurements/phase2_5.md` |
| Baseline before and after the leak fix | 1.00 → 0.842 dev, 0.438 test | [laptop] `docs/measurements/phase2.md`, `phase2_5.md` |
| Leak test | 18,340 items, 101 never healthy, 0 leaks | [laptop] `docs/measurements/phase2_5.md` |
| Local models' verified hypotheses | 0 of 145 | [laptop] ADR-000 |
| Ingestion ceiling | ~100,000 events/s; Python processors CPU-bound | [laptop] `docs/measurements/phase1.md` |
| Alert latency, fast-onset | 13.0-26.7 s (target < 30 s) | [laptop] `docs/measurements/phase2_5.md` |
| Baseline time to outcome | 1.3-3.5 s | [laptop] same |
| Agent model time per test run | 118 s median, 213 s max | [hosted] `docs/report-phase3.md` |
| Agent tokens per test run | 102k median, 126k max | [hosted] same |
| Budget | 20 tool calls, 150,000 tokens, 600 s | A41, A42 |
| Stack memory | 2.07 GB, 17 containers; qwen2.5:3b runner 2.2-2.4 GB | [laptop] `docs/measurements/phase2_5.md`, ADR-000 |
| Fixtures | 35 (19 dev, 16 test); injection 3 of 5 | A22, A44 |
| Guard checks | 69, all pass | `tools/guard_checks.out` |
| Tests | 189 unit, 33 integration, 4 viewer | [CI] |

## 7. Weak spots, and honest answers

| They ask | Say |
|---|---|
| "N=1? That's nothing." | Agreed: it's what the free tier allowed. The noise was measured (4 of 6 pairs flip), the rule was fixed in advance, and I don't claim the size of the loss, only its direction. |
| "Your agent is just a bad prompt." | Possibly: iteration was capped at one dev pass a day. But iteration C traded accuracy for budget compliance knowingly. The failure modes (abstaining, running out of calls, no conflicting answers) are structural, and they point to re-ranking, not more prompting. |
| "35 synthetic fixtures from your own demo system?" | Yes, and that's why the leak work matters: the data was made honest before anything was measured on it, and test was held out. It's still one demo system; I don't claim it generalizes. |
| "The verifier passed a false positive." | Yes, no_fault_002. The verifier guarantees support, not truth. That's stated and shown in the viewer. |
| "Injection 0 of 6 proves nothing." | Right: planted text barely reached the agent, so it measures exposure. The layered defences are shown by the adversarial unit tests, not by that rate. |
| "You skipped the UI and observability." | Deferred in A44, with reasons. The result doesn't depend on them. |
| "Who wrote the code?" | An AI coding agent, under my spec and ground rules; the decisions at the gaps were mine (section 2). |

## 8. Self-test

1. What makes a `log_pattern` claim fail even when the line really is in the logs?
2. Why can't the agent cite the baseline's tool calls, and what went wrong when it tried?
3. Name the three leaks found in the fixtures, in order.
4. What is the replay key, and why does it contain a placeholder?
5. What happens when the agent's tool-call budget runs out?
6. State the pre-registered decision rule and apply it to 1 / 4 / 11.
7. Why is the injection-influence rate weak evidence here?
8. Which fixture shows that the verifier guarantees support, not truth?
9. What is the throughput bottleneck, and what would you change first?
10. What would you build next, and how would you evaluate it?

### Answer key

1. The pattern must at least double against the equal-length window before. The cited queries must cover both windows, untruncated (A24).
2. The verifier requires every cited call to have the hypothesis's ranker (A15). Small models cited low numbers that belonged to the baseline; the fix was local numbering (A39, postmortem 004).
3. Fault-only log strings; `code.file.path` = `faults.py` on injected lines; the HTTP span from starting the batch job (postmortem 001).
4. sha256 of model, digest, canonical request and run index. The data boundaries are random per call, so they are replaced by a placeholder, or no request would ever repeat (A35).
5. One answer-only turn. Asking for tools again, or running out of tokens or time, degrades to the baseline's verified answer (A37).
6. Beats if wins − losses ≥ 3 and the mean is higher; loses in the mirror case; otherwise no measurable difference. 1 / 4 / 11: losses − wins = 3 and the mean is lower, so it loses.
7. Planted text reached the agent in 1 of 6 dev runs and 0 on test, so the with and without runs were mostly identical.
8. no_fault_002.
9. The CPU of the single-threaded Python processors, at ~100k events/s. Add partitions and one processor per partition.
10. The model re-ranks or explains the baseline's verified candidates. Frozen, pre-registered, test once, paired by fixture (ADR-000).
