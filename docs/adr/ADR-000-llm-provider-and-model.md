# ADR-000: LLM provider and model

**Status:** Accepted (Phase 3, model selection). Raw numbers: `docs/measurements/phase3/selection/`.

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
- **Model: `llama3.2:3b`** (Q4_K_M, digest in the cassettes).

## Candidates and measurements

Setup:

- Dev split, 19 fixtures, N = 1, same prompt and loop for all three (before iteration A, A39).
- Budget 20 tool calls, 60,000 tokens, 600 s wall time.
- ClickHouse and Postgres running; the demo stack stopped.
- Model time is the sum of each exchange's recorded `latency_ms` (`tools/agent_latency.py`), because
  fixtures replayed after a restart report replay time as their wall time.

| | qwen2.5:3b | **llama3.2:3b** | qwen2.5:1.5b |
|---|---|---|---|
| Top-1 judged / exact / service-only | 0.263 / 0.263 / 0.263 | 0.263 / 0.263 / 0.263 | 0.316 / 0.316 / 0.316 |
| Outcome correct | 5 / 19 | 5 / 19 | 6 / 19 |
| Agent hypotheses verified | 0 of 32 | 0 of 16 | 0 of 27 |
| Degraded runs | 3 (2 budget, 1 llm_unavailable) | **0** | 1 (llm_unavailable) |
| Runs with a parse failure (first attempt) | 12 | **4** | 19 |
| Model time per run, median (min–max) | 377 s (126–660) | 212 s (74–318) | 31 s (12–97) |
| Tokens per run, median | 17.5k | 42.3k | 5.2k |
| LLM calls / agent tool calls per run, median | 4 / 6 | 21 / 20 | 3 / 1 |
| Model runner RSS, max | 3.7 GB | 4.1 GB | 1.9 GB |
| Lowest host Available in the completed run | 1.26 GB | 2.03 GB | 2.67 GB |
| Paired vs baseline (top-1): wins / losses / ties | 1 / 12 / 6 | 2 / 13 / 4 | 2 / 12 / 5 |

The baseline in the same investigations scores top-1 0.842 (16/19), as it did in Phase 2.5.

- **None of the three produced a single verified hypothesis.** Every correct agent result is a correct
  `INSUFFICIENT_EVIDENCE`, or a run that degraded and showed the baseline.
- **The accuracy gaps are not differences.** 0.316 against 0.263 is one fixture.

## Why llama3.2:3b

- **Robust:** it is the only candidate with no degraded run, and it has the fewest parse failures (4,
  against 12 and 19).
- **It investigates:** a median of 20 tool calls, where qwen2.5:1.5b makes one call and then answers. A
  model that does not query cannot cite.
- **Fast enough:** 44% less model time per run than qwen2.5:3b at the same parameter count.
- **Fixable failures:** its rejected claims cluster in one fixable mistake (9 of 16 cite the timeline as
  evidence for a `log_pattern`). qwen2.5:3b's are spread across empty citations, baseline citations,
  wrong tools and malformed fields.
- **Cost:** 2.4 times qwen2.5:3b's tokens, and the most memory.
  - Its runner reaches 4.1 GB, against 2.2–3.4 GB for qwen2.5:3b at one parallel slot.
  - Twice the 1 GB rule stopped its run while Brave (2.1 GB) and WhatsApp's WebView (about 1.1 GB)
    were open. With them closed, the lowest Available was 2.03 GB.
  - Agent evals therefore run with those closed.

## Not run

- **qwen2.5:7b did not fit on a 16 GB laptop running the full stack.** The rule was to try it only if
  Available exceeded 6.5 GB after cleanup. It was 3,788 MB, with WSL capped at 4 GB and ClickHouse and
  Postgres running. It was not attempted.
- **The free-tier hosted comparison (DEV only)** has not been run. No `LLM_API_KEY` is configured. If one
  is set, it is run once and reported apart from the local model, never as the chosen agent.

## Memory notes

- **Ollama's default parallel slots:** by default Ollama reserved several parallel slots per model, each
  with its own context. qwen2.5:3b's runner used 4.1–4.4 GB that way, and host Available fell to 1.3 GB.
  With `OLLAMA_NUM_PARALLEL=1` it used 2.2–2.4 GB.
- **Eval harness peak memory:** two memory-floor stops during selection traced to the eval harness, not
  the model, and both were fixed.
  - Building the injection fixture's copy without the planted rows held every table in Python.
  - The Parquet re-execution (A26) ran next to the loaded model; it now runs after the model is unloaded.

## Consequences

- At about 3.5 minutes of model time per run, an N=5 dev eval (19 fixtures plus the injection fixtures'
  clean runs) takes about 6 hours, and the test eval about 5. Replay in CI takes minutes.
- The 120 s wall budget of §7.1 cannot be met on this hardware by any candidate that investigates; the
  budget defaults are re-measured on the chosen model in a SPEC amendment.
- A larger local model needs more RAM or a GPU. A hosted model needs a key and a network, and gives up
  the bit-exact local replay of the model digest. The interface allows either.
