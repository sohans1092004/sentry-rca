
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
