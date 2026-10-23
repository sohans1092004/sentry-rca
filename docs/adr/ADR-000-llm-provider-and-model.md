# ADR-000: LLM provider and model

**Status:** Accepted (Phase 3), revised twice: the local choice was corrected (see *Correction*), and the
evaluated agent moved to a free-tier hosted model by the user's decision when no local model produced a
verified hypothesis (see *Hosted model*). On test the frozen agent lost to the baseline (see *Test
result*). Raw numbers: `docs/measurements/phase3/`.

## Context

The agent (SPEC §7.4) needs a model that:

- runs at zero cost on the laptop that also runs the stack (i7-12700H, 14 cores, 16 GB RAM, Intel Iris Xe,
  **no NVIDIA GPU**, so CPU inference only);
- calls tools and writes the §8.1 JSON;
- can be replayed bit-for-bit in CI.

The phase rules make the choice on DEV fixtures only and stop a run if host Available memory falls
below 1 GB.

## Decision

- **Provider:** Ollama, native on the Windows host, behind
  `complete(messages, tools, temperature=0, schema=None)` (`investigation/llm.py`).
  - Temperature 0, seed 0, `num_ctx` 8192.
  - `OLLAMA_NUM_PARALLEL=1`, because the agent makes one call at a time.
- **Recording:** every exchange is recorded (`llm_exchanges` plus per-fixture cassettes), and CI replays
  only (A35).
- **Optional hosted provider:** an OpenAI-compatible one exists. It is off unless `LLM_API_KEY` is set,
  and none is required.
- **Local model: `qwen2.5:3b`** (Q4_K_M, digest in the cassettes), the zero-cost default. The first
  version of this ADR chose `llama3.2:3b`; see *Correction*.
- **Evaluated agent: `gemini-3.5-flash-lite`** on the Gemini API free tier, through the OpenAI-compatible
  provider (user's decision, 21 Oct). See *Hosted model*.

## Candidates and measurements

Setup:

- Dev split, 19 fixtures, N = 1, same prompt and loop for all three (before iteration A, A39).
- Budget 20 tool calls, 60,000 tokens, 600 s wall time.
- ClickHouse and Postgres running; the demo stack stopped.
- Model time is the sum of each exchange's recorded `latency_ms` (`tools/agent_latency.py`), because
  fixtures replayed after a restart report replay time as their wall time.

| | **qwen2.5:3b** | llama3.2:3b | qwen2.5:1.5b |
|---|---|---|---|
| Top-1 judged / exact / service-only | 0.263 / 0.263 / 0.263 | 0.263 / 0.263 / 0.263 | 0.316 / 0.316 / 0.316 |
| Outcome correct | 5 / 19 | 5 / 19 | 6 / 19 |
| Agent hypotheses verified | 0 of 32 | 0 of 16 | 0 of 27 |
| Degraded runs | 3 (2 budget, 1 llm_unavailable) | **0** | 1 (llm_unavailable) |
| Runs with a parse failure (first attempt) | 12 | **4** | 19 |
| Model time per run, median (min–max) | 377 s (126–660) | 212 s (74–318) | 31 s (12–97) |
| Tokens per run, median | 17.5k | 42.3k | 5.2k |
| LLM calls / agent tool calls per run, median | 4 / 6 | 21 / 20 | 3 / 1 |
| Agent tool calls rejected by scope / executed (all runs) | 55 / 88 | **303 / 9** | 14 / 5 |
| Distinct queries executed (all runs) | **81** | 9 | 5 |
| Model runner RSS, max | 3.7 GB | 4.1 GB | 1.9 GB |
| Lowest host Available in the completed run | 1.26 GB | 2.03 GB | 2.67 GB |
| Paired vs baseline (top-1): wins / losses / ties | 1 / 12 / 6 | 2 / 13 / 4 | 2 / 12 / 5 |

The baseline in the same investigations scores top-1 0.842 (16/19), as it did in Phase 2.5.

- **None of the three produced a single verified hypothesis.** Every correct agent result is a correct
  `INSUFFICIENT_EVIDENCE`, or a run that degraded and showed the baseline.
- **The accuracy gaps are not differences.** 0.316 against 0.263 is one fixture.

## Why qwen2.5:3b

- **It is the only candidate that investigates.** It ran 88 queries (81 distinct) across 19 runs.
  - llama3.2:3b ran 9. Of its 312 tool calls, 303 were rejected by the scope layer, mostly the same call
    repeated without `start`/`end`, or with `services` passed as a string. It looped on the rejection until
    the budget ran out, then answered `{"hypotheses": []}`.
  - qwen2.5:1.5b ran 5.
- **A model that runs no queries has no rows to cite.** So the agent can only get better through prompt
  and loop changes with qwen2.5:3b.
- **It fits:** 2.2–3.7 GB RSS, with host Available at least 1.26 GB in its completed run. Its median model
  time is 377 s per run.
- **Its weaknesses are the ones dev iteration targets:**
  - 12 first-attempt parse failures, all recovered by the constrained retry (A38);
  - empty `"all"` citations;
  - citations of the baseline's call numbers (A39);
  - 55 rejected calls, most missing `start`/`end` or `service`.

## Correction

- **What went wrong:** the first version of this ADR chose llama3.2:3b. It cited its zero degraded runs,
  its 4 parse failures and its median of 20 tool calls, and called the 20 calls "it investigates".
- **How it was found:** the first dev-iteration run with llama3.2:3b showed every call of a run rejected.
  Counting rejected against executed calls for the selection runs (table above) showed its 20 calls were
  almost all rejected repeats.
- **What the numbers actually meant:** its lack of degradation and parse failures came from running into
  the tool budget and answering with nothing.
- **The fix:** the selection criterion now counts executed queries, not issued calls. The choice is
  qwen2.5:3b. The aborted llama3.2:3b iteration run is not used.

## Not run

- **qwen2.5:7b did not fit on a 16 GB laptop running the full stack.** The rule was to try it only if
  Available exceeded 6.5 GB after cleanup. It was 3,788 MB, with WSL capped at 4 GB and ClickHouse and
  Postgres running. It was not attempted.
- **N=5 evals with the hosted model.** The free tier allows 500 requests a day for this model, and an
  investigation takes about 17. N=5 on dev and test would need about 3,200 requests, roughly a week of quota.
  The user chose N=1 on dev and test instead, with no paid tier (see *Hosted model*).

## Hosted model

- **Why it was added:** after model selection and two dev iterations, no local model had produced a single
  verified hypothesis. There were 145 agent hypotheses, all rejected. The user decided to evaluate a
  free-tier hosted model as the agent and to report the local result alongside it.
- **Which model:** `gemini-3.5-flash-lite` was the only current Gemini model that answered a tool call
  (21 Oct, 21:45 IST). The 2.5 models are closed to new keys. Gemini 3.x Flash, 3.1 Flash Lite and
  Gemma 4 31B returned 503 or 500.
- **Free-tier limits (AI Studio):** 15 requests per minute, 250K input tokens per minute, and **500
  requests per day**.
  - The client waits at least 4 s between calls and honours `Retry-After` (A41).
  - The daily limit is what restricts the evals to N=1.
- **Dev N=1, before iteration C:**
  - top-1 0.421 judged, 0.526 service-only, against the baseline's 0.842;
  - 5 of 10 agent hypotheses verified;
  - 4 runs degraded on the 150k-token budget;
  - paired by fixture: 2 wins, 10 losses, 7 ties.

  Raw numbers: `docs/measurements/phase3/hosted/dev-n1.json`.
- **Data sent to the provider:**
  - **It may keep it.** Free-tier Gemini API requests may be kept and used by Google to improve its
    products, under the API's free-tier terms. Paid-tier data is treated differently.
  - **What is sent:** every request carries the prompt, which is tool results drawn from the fixtures.
  - **The fixture data is entirely synthetic.** The telemetry of the demo services under injected faults
    is from this project's own test system: no real users, customers or production systems.
  - **No secrets are sent.** No credential or key is in any request body. The key travels only in the
    HTTP `Authorization` header.
  - **Checks:** `tools/secret_scan.py` and its test fail if a key-shaped string reaches the repository or
    a cassette, and a remove-the-guard check covers the scan.
  - **Production use:** a deployment on real telemetry would need a provider under paid or enterprise
    terms, or the local model.
- **Replay:** the model has no digest. Its name and endpoint stand in for one in the replay key. The
  provider can change the model behind the name, so recorded cassettes, not a re-run, are the reference.

## Test result (frozen agent, once)

**The agent loses to the baseline on test.** Frozen iteration C on `gemini-3.5-flash-lite`, test N=1,
16 fixtures: top-1 judged 0.250 against the baseline's 0.438; paired by fixture 1 win, 4 losses, 11 ties,
which meets the pre-registered loss condition (losses − wins ≥ 3 and a lower mean). It lost on dev as
well (2 / 12 / 5). Reasons, from the data:
- it abstains: "insufficient evidence" on 8 of 11 root-cause test fixtures;
- 11 of 16 test runs used all 20 tool calls and answered on the forced final turn;
- it never answered CONFLICTING_EVIDENCE (0 of 6 such runs on dev and test);
- confounded fixtures: top-1 0.111, against 0.429 on clean ones.

At N=1, with identical dev runs changing their top answer in 4 of 6 pairs, the size of the loss is not
established; its direction is the same on dev, on test and at every iteration. No other version was run
on test. Full tables: `docs/report-phase3.md`; raw: `docs/measurements/phase3/test/`.

## Memory notes

- **Ollama's default parallel slots:** by default Ollama reserved several parallel slots per model, each
  with its own context. qwen2.5:3b's runner used 4.1–4.4 GB that way, and host Available fell to 1.3 GB.
  With `OLLAMA_NUM_PARALLEL=1` it used 2.2–2.4 GB.
- **Eval harness peak memory:** two memory-floor stops during selection traced to the eval harness, not
  the model, and both were fixed.
  - Building the injection fixture's copy without the planted rows held every table in Python.
  - The Parquet re-execution (A26) ran next to the loaded model; it now runs after the model is unloaded.

## Consequences

- At about 6 minutes of model time per run, an N=5 dev eval (19 fixtures plus the injection fixtures'
  clean runs) takes about 10–11 hours, and the test eval about 9. Replay in CI takes minutes.
- The 120 s wall budget of §7.1 cannot be met on this hardware by any candidate that investigates; the
  budget defaults are re-measured on the chosen model in a SPEC amendment.
- A larger local model needs more RAM or a GPU. A hosted model needs a key and a network, and gives up
  the bit-exact local replay of the model digest. The interface allows either.
