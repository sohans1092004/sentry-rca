# Phase 3 report: the LLM agent

**Result: the agent loses to the baseline on test.** Under the decision rule pre-registered before the
test run (`docs/analysis-plan-phase3.md`), it loses: paired by fixture on top-1 judged it has 1 win,
4 losses and 11 ties (losses − wins = 3), and its top-1 judged is lower, 0.250 against 0.438. It also
lost on dev at every stage. The margin sits exactly on the rule's threshold, and at N=1 identical
repeated runs changed their top answer in 4 of 6 dev pairs, so a re-run could land on "no measurable
difference"; it would not plausibly land on a win. The verifier held throughout: no gold claim was
rejected and no out-of-scope evidence was allowed.

Phase 4 has not been started.

## What was built

| Piece | Where |
|---|---|
| Provider interface `complete(messages, tools, temperature, schema, timeout_s)`; Ollama (default) and an OpenAI-compatible hosted provider, disabled unless `LLM_API_KEY` is set | `investigation/llm.py` |
| Recording and replay: every exchange committed to `llm_exchanges` before use, plus per-fixture cassettes; replay key = sha256(model, digest, canonical request with the data boundary replaced by a placeholder, run index); a replay miss raises | `investigation/llm.py`, `common/migrations/postgres/0007_llm_exchanges.sql`, A35 |
| Agent loop (ADR-010): fixed system prompt, incident context as fields, closed cause-kind list, untrusted data in per-call random `<<DATA-…>>` boundaries, strict §8.1 JSON with one retry then degrade, schema-constrained answer turns, budget on tool calls / tokens / wall time with a final answer turn, the agent's own call numbering so it can cite only its own calls, one verifier-feedback repair turn | `investigation/agent.py`, A36–A42 |
| Orchestrator: baseline first, then the agent; a degraded agent shows the verified baseline as `degraded_baseline` | `investigation/orchestrator.py:149` |
| Verifier rule: a root cause must be in scope and have a non-runbook claim about it (A36) | `investigation/verifier.py` |
| Eval harness: agent runs, clean copies of injection fixtures, per-fixture paired comparison with an exact sign test, rejection reasons, a per-database read-only ClickHouse user | `evals/harness.py`, `investigation/cli.py` |
| Secret scan over the repository and every cassette, with a test and a guard | `tools/secret_scan.py`, `tests/unit/test_secrets.py` |
| CI `agent-replay` job: the frozen agent on all 35 fixtures from the cassettes, no key, no model | `.github/workflows/ci.yml` |
| Kill-the-model demonstration | `tools/kill_llm_demo.py`, `docs/measurements/phase3/kill-ollama-demo.txt` |
| ADR-000 (provider and model), ADR-010 (hand-written tool loop), walkthrough | `docs/adr/`, `docs/walkthrough-phase3.md` |

## Model comparison (dev only)

Hardware: i7-12700H, 16 GB RAM, Intel Iris Xe, no NVIDIA GPU; Ollama 0.40.7 on CPU. Details and raw
numbers: ADR-000 and `docs/measurements/phase3/selection/`.

| Model | top-1 judged (dev N=1) | agent hypotheses verified |
|---|---|---|
| qwen2.5:3b (local, chosen local default) | 0.263 | 0 |
| llama3.2:3b (local) | 0.263 | 0 |
| qwen2.5:1.5b (local floor) | 0.316 | 0 |
| qwen2.5:7b | not run: did not fit on a 16 GB laptop running the full stack | — |
| gemini-3.5-flash-lite (hosted free tier, before C) | 0.421 | 5 of 10 |
| **gemini-3.5-flash-lite, iteration C (frozen)** | 0.316 | 4 of 6 |
| baseline | 0.842 | — |

Across selection and two local iterations, 145 local agent hypotheses were produced and none verified. The hosted model was adopted by the user's decision
(A41). It runs at N=1 because the free tier allows 500 requests a day.

## Dev iterations (each logged with its result)

| Iteration | Change | Dev result |
|---|---|---|
| A (qwen2.5:3b) | compaction, schema-constrained retry (A38) | partial, 9 fixtures; 0 verified |
| B (qwen2.5:3b) | tool parameters described, rejection hints, reply cap (A40) | partial, 16 fixtures; rejected tool calls 55/143 → 16/92; 0 of 9 verified |
| hosted, before C | same loop on gemini-3.5-flash-lite (A41) | top-1 0.421; 4 runs on the token budget; paired vs baseline 2/10/7 |
| C (frozen) | claims tied to the anomaly onset, rise checked first, truncated results unusable for log claims, smaller context (A42) | top-1 0.316; 0 on the budget; tokens median 87k (from 130k); paired vs before C 2/4/13; vs baseline 2/12/5 |

Changes stopped when they stopped helping: iteration C met its budget and rejection targets but was not
an accuracy gain, and the free-tier quota left one dev pass per day.
Logs: `docs/measurements/phase3/iterations/`.

## Dev and test, frozen agent against the baseline

The agent's numbers are the result shown to a person (the agent's when it completes; there were no
degraded runs in either split). The baseline is the frozen baseline in the same investigations; its
test numbers equal the accepted Phase 2.5 test result exactly (0.4375 / 0.3125 / 0.5).

| | dev agent | dev baseline | **test agent** | **test baseline** |
|---|---|---|---|---|
| fixtures (N) | 19 (1) | 19 (1) | 16 (1) | 16 (1) |
| top-1 judged | 0.316 | 0.842 | **0.250** | **0.438** |
| top-1 exact (service, kind) | 0.316 | — | 0.188 | 0.313 |
| top-1 service-only | 0.316 | — | 0.250 | 0.438 |
| top-3 judged | 0.316 | 0.842 | 0.250 | 0.500 |
| outcome correct | 7 / 19 | 13 / 19 | 5 / 16 | 8 / 16 |
| clean fixtures, top-1 | 0.400 (10) | — | 0.429 (7) | 0.571 (7) |
| confounded fixtures, top-1 | 0.222 (9) | — | 0.111 (9) | 0.333 (9) |
| spread | N=1: none measurable; see the noise line below | | | |

**N=1 noise (pre-registered):** on dev, identical repeated runs changed their top answer in 4 of 6
pairs (`docs/measurements/phase3/iterations/injcheck-hosted-dev-3x3.json`). No difference of one or two
fixtures is meaningful here.

### Paired by fixture (top-1 judged)

| Split | wins | losses | ties | sign test p (description only) | rule verdict |
|---|---|---|---|---|---|
| dev | 2 | 12 | 5 | 0.013 | loses |
| **test** | **1** | **4** | **11** | 0.375 | **loses** (losses − wins = 3, mean lower) |

Test outcome-correct: 1 win, 4 losses, 11 ties.

| Test fixture | expected | agent rank 1 | baseline rank 1 | top-1 |
|---|---|---|---|---|
| ambiguous_t01 | conflicting | none | payments / bad_deploy | loss |
| ambiguous_t02 | conflicting | none | payments / dependency_outage | loss |
| ambiguous_t03 | conflicting | none | orders / bad_deploy | tie (both wrong) |
| bad_deploy_t01 | root cause | inventory / bad_deploy | inventory / bad_deploy | tie (both right) |
| cache_stampede_t01 | root cause | none | orders / bad_deploy | tie (both wrong) |
| cache_stampede_t02 | root cause | inventory / pool_exhaustion | inventory / slow_query | tie (both right, judged) |
| config_change_t01 | root cause | none | none | tie (both wrong) |
| config_change_t02 | root cause | gateway / bad_deploy | gateway / bad_deploy | tie (both wrong) |
| connection_refused_t01 | root cause | none | none | tie (both wrong) |
| connection_refused_t02 | root cause | none | gateway / memory_leak | tie (both wrong) |
| cpu_throttling_t01 | root cause | none | orders / pool_exhaustion | loss |
| cpu_throttling_t02 | root cause | none | none | tie (both wrong) |
| no_fault_t01 | insufficient | none | inventory / bad_deploy | **win** |
| noisy_neighbor_t01 | insufficient | none | none | tie (both right) |
| pool_exhaustion_t01 | root cause | none | inventory / pool_exhaustion | loss |
| slow_query_injection_t01 | root cause | none | inventory / bad_deploy | tie (both wrong) |

### Outcome confusion (rows expected, columns given)

| Test | agent: root cause | agent: insufficient | agent: conflicting | baseline: root cause | baseline: insufficient | baseline: conflicting |
|---|---|---|---|---|---|---|
| root cause (11) | 3 | 8 | 0 | 7 | 3 | 1 |
| insufficient (2) | 0 | 2 | 0 | 1 | 1 | 0 |
| conflicting (3) | 0 | 3 | 0 | 3 | 0 | 0 |

Dev (agent): root cause 3 / 8 / 0; insufficient 1 / 4 / 0; conflicting 0 / 3 / 0.

### Why it loses (from the data, not a guess)

- **It abstains.** On test it answered "insufficient evidence" on 8 of 11 root-cause fixtures (dev: 8
  of 11). Iteration C made it require a sharp rise at the anomaly onset before claiming anything; that
  removed false claims and budget overruns, and also most true ones.
- **It runs out of looking.** 11 of 16 test runs (dev: 8 of 19) used all 20 tool calls and answered on
  the forced final turn; 7 used the repair turn.
- **It never says CONFLICTING_EVIDENCE** (0 of 6 such runs across dev and test). It does not propose two
  competing causes, which is what that outcome needs.
- **Confounders hurt it most:** top-1 0.111 on the 9 confounded test fixtures against 0.429 on the 7
  clean ones.
- Its one win is a no-fault fixture where abstaining is right and the baseline proposed a harmless
  deploy.
- The free tier limited this to N=1 and one dev pass a day, so the prompt saw fewer iterations than
  planned; and the local models, which had no quota, never produced a verified hypothesis.

## Verifier, injection, cost, robustness

| | dev (C) | test |
|---|---|---|
| agent hypotheses verified / rejected | 4 / 2 | 4 / 2 |
| rejection reasons (agent) | a deploy claim with no anomaly onset after it (1); a log claim citing no row in its window (1) | a log query not covering the window and the window before it (1); a deploy claim with a null time, rejected as malformed (1) |
| baseline hypotheses rejected | — | 0 of 40 |
| gold claims rejected / out-of-scope allowed / backend mismatches | 0 / 0 / 0 | 0 / 0 / 0 |
| injection influence (rank 1 changed with vs without planted rows) | 0 of 6 (3+3 check); 1 of 2 in the dev pass | 0 of 1 |
| injection exposure (prompts with planted text) | 1 of 66 in the 3+3 check | **0** of 10 |
| model time per run, median / max (recorded) | 86 s / 371 s | 118 s / 213 s |
| tokens per run, median / max | 87k / 123k | 102k / 126k |
| LLM calls / agent tool calls, median | 15 / 19 | 18.5 / 20 |
| parse failures (runs) | 1 | 0 |
| degraded runs | 0 | 0 |
| replay misses (CI) | 0 required | 0 required |

Time to the first verified hypothesis is the baseline's, about 2 s, in every investigation (the
baseline runs first). Model time comes from the recorded exchange latencies (`tools/agent_latency.py`):
13 test fixtures were replayed in the completed run (below), so its wall-clock fields are replay time.

**Injection, as measured:** planted text reached the agent in 1 of 6 runs of the dev 3+3 check and in
none of the test run, so these checks measure exposure more than resistance. In every hosted run where
planted text was seen (5 on dev), the planted cause (gateway, DNS, TLS or certificate) was never named.
Adversarial unit tests with an obedient fake model (another tenant, an out-of-scope service, an
out-of-list kind, a cause with no evidence) are rejected by scope, schema and verifier respectively
(`tests/unit/test_agent.py`).

## The test run, and its one deviation (A43)

The scheduled task started the one test run at 12:35 IST on 23 Oct. It was terminated from outside
after 13 of 16 fixtures (task result `0xC000013A`, a console-close or Ctrl-C exit; the logs do not say
what sent it; no sleep, crash or out-of-memory event was logged). By the user's decision it was
completed the same afternoon with the identical command at the same `agent-frozen` commit: the 13
finished fixtures replayed from their recorded responses (identical requests, so no second draw) and
were checked identical to the first attempt (outcome, every hypothesis with its verifier status,
exchange count: 13 of 13); only the 3 unfinished fixtures and the injection clean copy called the model.
`docs/measurements/phase3/test/`.

## Failure handling

- **Model killed mid-investigation** (`tools/kill_llm_demo.py`, local qwen2.5:3b): killed after 2
  committed exchanges; the investigation ended `degraded_baseline` (`llm_unavailable`) showing the
  baseline's verified inventory / pool_exhaustion; nothing was lost (26 baseline and 4 agent tool calls,
  2 exchanges, 3 hypotheses kept). `docs/measurements/phase3/kill-ollama-demo.txt`.
- **Malformed output:** one retry, schema-constrained, then `degraded_baseline` (`parse`)
  (`tests/integration/test_phase3.py`).
- **Budget:** a final answer-only turn, then `degraded_baseline` (`budget`).

## Guard checks

All 67 remove-the-guard checks pass (23 Oct, after the test run; `tools/guard_checks.out`): each guard
removed makes its test fail by showing the unsafe behaviour, and restored makes it pass. The ten Phase 3
guards:

| Guard | Unsafe behaviour shown when it is removed |
|---|---|
| agent_budget_tool_calls | a looping agent gets more than `tool_calls` tool calls executed |
| agent_budget_wall_time | a slow looping agent does not stop at the wall-time limit |
| degrade_path | an LLM failure does not end `degraded_baseline` with the verified baseline answer |
| replay_miss_loud | a replay miss falls through to a live model instead of raising |
| replay_key_whole_request | a changed request is answered from another request's recording |
| output_schema | an out-of-list cause kind, or a hypothesis without claims, is stored |
| untrusted_data_framing | telemetry text appears outside its data block |
| same_ranker_citations | an agent hypothesis citing a baseline tool call is accepted |
| cause_service_in_scope | a root cause outside the scope, or with no claim about it, is accepted |
| secret_scan | a key planted in a cassette is not found |

Lint, format and types are clean; 189 unit and 33 integration tests pass. The secret scan finds 0
key-shaped strings in the repository and cassettes.

## Memory

- Ollama native on Windows; `OLLAMA_NUM_PARALLEL=1` (the default doubled the runner's RSS: 4.1–4.4 GB
  against 2.2–2.4 GB for qwen2.5:3b). WSL capped at 4 GB.
- Local evals ran with the demo stack stopped and a watchdog that stops the eval below 1 GB available;
  it stopped six runs (three by apps left open, three by my own code loading data beside the model, all
  fixed). Lowest available during the hosted dev pass: 2,112 MB.
- The hosted test run has no local model. Available memory was 2,695 MB at 12:40 and 2,946 MB at 16:41;
  the stage-2 runner does not run the watchdog, so there is no continuous trace for it.

## Bugs found in Phase 3

- The random data boundary made every request unique, so replay could never hit (A35: placeholder in the
  hash).
- The agent cited the baseline's tool-call numbers (A39: its own numbering).
- Wall time was not enforced inside a model call (A39: per-call timeout).
- The injection clean copy reloaded every table; backend agreement and fixture loads ran beside the model
  (memory stops; fixed by copying files, deferring agreement, unloading the model first).
- Concurrent evals revoked a shared read-only ClickHouse user (per-database users).
- Replayed runs reported replay latency (`tools/agent_latency.py`).
- I misread model selection and first chose llama3.2:3b on its tool-call count, though 303 of its 312
  calls were rejected (ADR-000, *Correction*).

## Spec changes

A35–A43 (`docs/SPEC.md`, Amendments). A41 moves the evaluated agent to the hosted free tier at N=1; A42
is the frozen iteration C; A43 records the test-run completion. No change after the test run touched the
agent, the verifier or the analysis.

## Not sure about

- **The size of the loss.** It is exactly at the rule's threshold at N=1, with large run-to-run variation.
  The direction is consistent across dev, test and every iteration; the magnitude is not established.
- **Injection resistance.** Exposure was too low to measure it on test.
- **Replay stability of the hosted model.** It has no digest; the cassettes, not a re-run, are the
  reference. A re-run on another day may differ.
- **What killed the first test attempt.** Not identified from the logs.
- **The API key** was typed into this session and should be revoked now that the hosted runs are done.
