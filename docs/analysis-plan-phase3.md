# Phase 3 pre-registered analysis plan

**Status:** final, committed with the `agent-frozen` tag on 22 Oct 2026, before the one test run. Nothing below may change after the test run. Any later
analysis is labelled post-hoc in SPEC, with the before and after numbers.

## Selection rule: which version is frozen, and why

- **Frozen: iteration C** (A42), on `gemini-3.5-flash-lite` (A41). The user approved the freeze on 22 Oct
  2026 after reviewing the Day 1 dev results (`docs/measurements/phase3/iterations/iterC-day1.md`).
- **Reason:**
  - budget compliance: 0 of 19 dev runs hit the budget, against 4 before C;
  - lower token use: median 87k tokens per run, against 130k.
- **The dev accuracy difference is within run-to-run noise.** Paired by fixture, C against before C:
  2 wins, 4 losses, 13 ties. Identical repeated runs changed their top answer in 4 of 6 pairs.
- **The earlier version scored 2 more fixtures on dev:** top-1 judged 0.421 (8 of 19), against C's
  0.316 (6 of 19). This is recorded because C was not chosen on accuracy.
- **Only C runs on test.** No other version (before C, the local models, any later change) will be run on
  the test split. The test split is run once, at N=1.

## What is compared

- **Agent:** the frozen agent (model, prompt, budget, parser and tool descriptions at `agent-frozen`).
- **Baseline:** the frozen baseline (`baseline-frozen`, `investigation/baseline.py` sha256 `d761cdaf625d`)
  under the current verifier.
  - Its results come from the same investigations, since the orchestrator always runs it first.
  - They are also checked against an `rca eval` baseline run on the same commit.
- **Data:**
  - Dev split: 19 fixtures, used for every development choice.
  - Test split: 16 fixtures, never seen by the agent before the run.
  - **N = 1** run per fixture, each split evaluated once. §12.3's N=5 does not fit the free tier's 500
    requests a day (A41).
  - Injection fixtures are also run without their planted rows (§12.4).
- **What "the result" means:** the result shown to a person. That is the agent's verified result when
  it completes, and the baseline's when it degrades. *Agent-only* accuracy is also reported, counting a
  degraded run as wrong.

## Metrics (for each split, and for clean and confounded fixtures separately)

1. **Top-1 accuracy** (at N=1, a single value per split; the spread fields are 0 and say nothing), in
   three ways:
   - judged (closed list, A23; new kinds judged on service);
   - exact (service, kind);
   - service-only.
2. **Top-3 accuracy**, judged and exact.
3. **Outcome confusion matrix** (expected × actual over all runs) and the number of runs whose outcome
   is correct.
4. **Per-fixture paired comparison, agent vs baseline**, for both top-1 judged and outcome-correct:
   - each fixture's result for each ranker (correct or not, N=1);
   - a verdict of win, loss or tie (more, fewer or equal correct runs);
   - tallies of wins, losses and ties;
   - an exact two-sided sign test over the non-tied fixtures, reported as a description only.
5. **Verifier:** the rejection rate of agent hypotheses, and failed claims by claim type with their
   grouped reasons. The same for the baseline.
6. **Injection influence (§12.4):** the fraction of runs where rank 1 differs with and without the
   planted rows. Test has one injection fixture (`slow_query_injection_t01`) and dev has two, so this is
   reported as counts, together with **exposure**: how many of the agent's prompts contained planted
   text (`llm_exchanges` requests). When nothing planted reaches the prompt, the run without planted rows
   sends identical requests and gets the recorded responses back, so it cannot differ. Reported as
   measured on dev: planted text reached the agent in 1 of 6 runs of the 3+3 check, so that check
   measures exposure more than resistance; in every hosted dev run where planted text was seen (5), no
   agent hypothesis named the planted cause (gateway, DNS, TLS or certificate).
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

## N=1 noise (written before the test run)

- **Reference:** next to every test number, the report shows the measured dev run-to-run variation.
  Identical repeated runs changed their top answer in 4 of 6 pairs (2 injection fixtures × 3 runs,
  `injcheck-hosted-dev-3x3.json`). The model is not deterministic at temperature 0.
- **One or two fixtures mean nothing.** No difference of one or two fixtures is called meaningful in
  either direction: agent vs baseline, test vs dev, or clean vs confounded.
- **The sign test is a description only.** At N=1 each fixture is one draw, so a fixture's win or loss can
  flip on a re-run.

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
| model | `gemini-3.5-flash-lite` (Gemini API free tier, OpenAI-compatible endpoint) |
| model digest | `hosted:https://generativelanguage.googleapis.com/v1beta/openai` (no digest; A41) |
| `investigation/agent.py` sha256 (LF) | `438a72449d697e0b30c0da1c83b01c306134166559eed8b0d432bbdef8c5935a` |
| `investigation/llm.py` sha256 (LF) | `8986bfbc75e56847bd7f85af139d07330fe50fed4ef5df236f9d26320cbd73d4` |
| `investigation/verifier.py` sha256 (LF) | `7f72c85b31e28e79c68f6c3d750162f6e6221b3e0a094af7ab4c06fc0d64283b` |
| `investigation/orchestrator.py` sha256 (LF) | `6785bad4e71eba752ddcae12ec5751464626e4a8bd28089aa8ab14cbf93cee5e` |
| budget (tool calls / tokens / wall s) | 20 / 150,000 / 600 |
| N | 1 |
| client spacing | `LLM_MIN_INTERVAL_S` = 4 s |
| replay cassettes | `evals/cassettes/gemini-3.5-flash-lite-frozen/` (dev: copy of the iteration C pass; test: written by the one test run) |
| test command | `rca eval --ranker agent --provider hosted --model gemini-3.5-flash-lite --llm record --split test --n 1 --wall-s 600 --max-tokens 150000 --tag frozen` (`tools/daily_runs.ps1` stage 2) |
