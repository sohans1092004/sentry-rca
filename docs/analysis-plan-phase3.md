# Phase 3 pre-registered analysis plan

**Status:** draft while the agent is developed on dev. It is final when committed together with the
`agent-frozen` tag, before the one test run. Nothing below may change after the test run. Any later
analysis is labelled post-hoc in SPEC, with the before and after numbers.

## What is compared

- **Agent:** the frozen agent (model, prompt, budget, parser and tool descriptions at `agent-frozen`).
- **Baseline:** the frozen baseline (`baseline-frozen`, `investigation/baseline.py` sha256 `d761cdaf625d`)
  under the current verifier.
  - Its results come from the same investigations, since the orchestrator always runs it first.
  - They are also checked against an `rca eval` baseline run on the same commit.
- **Data:**
  - Dev split: 19 fixtures, used for every development choice.
  - Test split: 16 fixtures, never seen by the agent before the run.
  - N = 5 runs per fixture, each split evaluated once.
  - Injection fixtures are also run without their planted rows (§12.4).
- **What "the result" means:** the result shown to a person. That is the agent's verified result when
  it completes, and the baseline's when it degrades. *Agent-only* accuracy is also reported, counting a
  degraded run as wrong.

## Metrics (for each split, and for clean and confounded fixtures separately)

1. **Top-1 accuracy**, as mean, standard deviation and min–max over the 5 runs, in three ways:
   - judged (closed list, A23; new kinds judged on service);
   - exact (service, kind);
   - service-only.
2. **Top-3 accuracy**, judged and exact.
3. **Outcome confusion matrix** (expected × actual over all runs) and the number of runs whose outcome
   is correct.
4. **Per-fixture paired comparison, agent vs baseline**, for both top-1 judged and outcome-correct:
   - each fixture's count of correct runs out of 5 for each ranker;
   - a verdict of win, loss or tie (more, fewer or equal correct runs);
   - tallies of wins, losses and ties;
   - an exact two-sided sign test over the non-tied fixtures, reported as a description only.
5. **Verifier:** the rejection rate of agent hypotheses, and failed claims by claim type with their
   grouped reasons. The same for the baseline.
6. **Injection influence (§12.4):** the fraction of runs where rank 1 differs with and without the
   planted rows. Test has one injection fixture and dev has two, so this is reported as counts.
7. **Latency (ms):**
   - to the first verified hypothesis of the investigation (the baseline's, when it has one);
   - to the agent's first verified hypothesis;
   - to the outcome;
   - each as median, mean, min and max.
8. **Cost:** tokens (in + out), LLM calls and agent tool calls per run.
9. **Robustness:**
   - parse failures (first attempts that failed) and runs with one;
   - degraded runs by reason (`llm_unavailable`, `parse`, `budget`);
   - replay misses, which must be 0 in the CI replay.
10. **Integrity, which must hold:**
    - 0 gold claims rejected;
    - 0 out-of-scope evidence allowed;
    - 0 backend-agreement mismatches;
    - an unchanged eval database hash.

## Decision rule (written before the test run)

- The agent **beats** the baseline on a split only if both of these hold:
  - on top-1 judged, the paired tally has **wins − losses ≥ 3 fixtures**;
  - the mean top-1 judged is higher.
- It **loses** under the mirror-image condition. Anything else, including a net difference of one or
  two fixtures, is reported as **no measurable difference**.
- The test-split result is the headline. A dev result alone is never called an improvement, because
  every agent choice was made on dev.
- If the agent does not beat the baseline on test, README and the Phase 3 report say so plainly, with
  the numbers (§12.5 reporting rule).

## Fixed before the run

At the freeze, the table below is filled in with the model, its digest, the prompt and loop source
hashes, the budget and the replay cassette directory.

| Item | Value |
|---|---|
| model | (at freeze) |
| model digest | (at freeze) |
| `investigation/agent.py` sha256 (LF) | (at freeze) |
| `investigation/llm.py` sha256 (LF) | (at freeze) |
| budget (tool calls / tokens / wall s) | (at freeze) |
| N | 5 |
