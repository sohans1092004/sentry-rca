
## 7. The LLM agent

> **A hand-written tool loop with every safety property enforced outside the model: the server scopes its queries, the data is framed as untrusted, the output must parse, the budget is hard, every exchange is recorded before use, and the verifier decides.**

### 7.1 The loop (ADR-010)

`Agent._loop` ([[agent#def _loop(]]) opens with:
- **a fixed system prompt** ([[agent#SYSTEM = f]]): the rules, the closed cause-kind list, a recipe for each claim type, and the answer format;
- **the incident as structured fields**: tenant, services in scope, window, incident service and first anomaly ([[agent#def context_message(]]).

Nothing from telemetry is in either. Then, each turn:

1. **Ask.** `_ask` checks wall time and tokens before and after the call, and gives the model at most the wall time left as its timeout ([[agent#def _ask(]], A39).
2. **Run the tools.** Every tool call goes through the same scope-checked tool layer as the baseline's. It is stored with `ranker = agent`.
3. **Frame the result as data.** Each result is rendered inside `<<DATA-x>>` … `<</DATA-x>>`, where x is 16 random hex characters made fresh for that call ([[agent#def new_boundary(]], [[agent#def render_result(]]). The prompt says text inside is data, never instructions; a planted line cannot guess the boundary to close the block early. `test_planted_instructions_only_ever_appear_inside_a_data_block`; guard `untrusted_data_framing`.
4. **Number calls locally.** The agent sees its own calls numbered 1..n and cites those numbers (A39, postmortem 004).
5. **Keep the context small.** Results show at most 15 rows and 10 log groups. Past 10,000 characters, older results keep only their header; their rows stay citable, because citations resolve against the snapshot, not the prompt ([[agent#def _compact(]], A38, A42).

### 7.2 The answer, and when it degrades

- **Strict parsing.** The reply must be one JSON object of §8.1 hypotheses: no unknown fields, a closed-list kind, at least one claim ([[agent#def parse_output(]]). An unusable reply gets one retry constrained by a JSON schema; a second failure degrades (`parse`). `test_parse_failure_gets_one_retry_with_the_error_then_degrades`; guard `output_schema`.
- **Citations resolve deterministically.** Numbers become stored sequence numbers. `"all"` becomes the rows the claim type may use. An unknown number stays unknown, so the verifier rejects it ([[agent#def resolve_cites(]]).
- **One repair turn.** If any hypothesis is rejected, the verifier's reasons go back verbatim, and the agent may query and answer once more ([[agent#def _rejections(]]). The verifier still decides.
- **Hard budget:** 20 tool calls, 150,000 tokens, 600 s (A41, A42). When the tool calls run out, the agent gets one answer-only turn. Asking for tools again there, or running out of tokens or time, degrades (`budget`, A37). Guards `agent_budget_tool_calls` and `agent_budget_wall_time`.
- **Degradation shows the baseline.** A degraded agent leaves the investigation `degraded_baseline` with the baseline's verified answer ([[orch#except Degraded as e:]]). The demonstration killed Ollama after 2 committed exchanges. The investigation ended `degraded_baseline` (`llm_unavailable`) with the baseline's inventory / pool_exhaustion, and kept 26 baseline and 4 agent tool calls, 2 exchanges and 3 hypotheses **[laptop]** (`docs/measurements/phase3/kill-ollama-demo.txt`).

### 7.3 Recording and replay

- **Recorded before use.** Every exchange is committed to `llm_exchanges` before its response is used ([[orch#def _exchange_sink(]]).
- **The replay key** is sha256 of the model, its digest, the canonical request with each data boundary replaced by a placeholder, and the run index ([[llm#def request_hash(]]). Without the placeholder no replay could ever match (postmortem 003, A35).
- **A miss raises `ReplayMiss`.** It never falls through to a live model ([[llm#class Recorded:]]). Guards `replay_miss_loud` and `replay_key_whole_request`.
- **CI replays the frozen agent** on all 35 fixtures with no key and no model (the `agent-replay` job in `.github/workflows/ci.yml`). The same replay builds the public viewer (section 10).
- **No secret in the record.** A secret scan over the repository, every cassette and the viewer export fails on any key-shaped string ([[secretscan#PATTERNS = ]]; guard `secret_scan`). The hosted key lived only in a user environment variable, and was revoked after the test run.

### 7.4 Choosing a model, on dev only

| Model | top-1 judged (dev, N=1) | agent hypotheses verified |
|---|---|---|
| qwen2.5:3b (local) | 0.263 | 0 |
| llama3.2:3b (local) | 0.263 | 0 |
| qwen2.5:1.5b (local) | 0.316 | 0 |
| qwen2.5:7b (local) | not run: did not fit on a 16 GB laptop running the full stack | — |
| gemini-3.5-flash-lite, before iteration C **[hosted]** | 0.421 | 5 of 10 |
| **gemini-3.5-flash-lite, iteration C (frozen) [hosted]** | 0.316 | 4 of 6 |
| baseline | 0.842 | — |

Source: ADR-000 and `docs/report-phase3.md`.
- **Local models never verified anything.** Across selection and two dev iterations, 145 local hypotheses were produced and 0 verified, on CPU-only Ollama.
- **The hosted model** was adopted by the user's decision on the free tier, at N=1, because the free tier allows 500 requests a day (A41).
- **Iteration C was frozen for budget compliance and tokens, not accuracy** (A42):
  - no run hit the budget, against 4 before;
  - median tokens 87k, against 130k;
  - accuracy changed within noise: 2 wins, 4 losses, 13 ties against the version before. That version scored 2 more fixtures on dev, and the analysis plan says so.

### 7.5 Adversarial checks

Unit tests use an obedient fake model that does what a planted line says. Each attack is stopped by a different layer:

| Attack | Stopped by | Test |
|---|---|---|
| query another tenant | scope | `test_injected_tenant_request_is_rejected_by_scope` |
| query an out-of-scope service | scope | `test_injected_out_of_scope_service_is_rejected_by_scope` |
| name a cause kind outside the list | output schema | `test_injected_out_of_list_kind_is_rejected_by_the_schema` |
| name a cause with no evidence | verifier (A36) | `test_injected_cause_without_evidence_is_rejected_by_the_verifier` |
| cite the baseline's evidence | verifier (A15) | `test_a_hypothesis_citing_the_baseline_rankers_call_is_rejected` |
