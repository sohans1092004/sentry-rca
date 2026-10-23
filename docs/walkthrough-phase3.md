# Phase 3 walkthrough: one investigation with the agent

For a reader who did not write the code. This follows one real test investigation, `bad_deploy_t01`:
a bad deploy of inventory makes its requests slow, the gateway SLO rule opens an incident on the
gateway, and the frozen agent (`agent-frozen`, gemini-3.5-flash-lite, iteration C) finds inventory /
bad_deploy, and the verifier confirms it. Investigation `a3cd9429-d8b2-4be4-b7aa-37c65b4de1ff` of eval
run `381e25e3` (`docs/measurements/phase3/test/`). `rca show <id>` prints everything below.

Phase 2's walkthrough (`docs/walkthrough-phase2.md`) covers the trigger, the scope and the baseline;
this one starts where the agent comes in.

## 1. Baseline first, always

`investigate()` (`investigation/orchestrator.py:149`) runs the frozen baseline before the agent
(`:178`), stores its hypotheses and result, and only then builds the agent (`:188`). So a verified
answer exists before any model is called: here the baseline made tool calls #1–#24 in 2.1 s and
verified inventory / bad_deploy at rank 1.

The agent gets:
- a provider wrapped by the recorder, whose sink commits every exchange to `llm_exchanges` before the
  response is used (`orchestrator.py:219`);
- the incident's service and first-anomaly time as fields (`:189`);
- the budget: 20 tool calls, 150,000 tokens, 600 s (A41).

## 2. What the model is told

`Agent._loop` (`investigation/agent.py:474`) starts the conversation with two messages:
- the fixed system prompt `SYSTEM` (`agent.py:72`): the rules, the closed list of cause kinds, how to
  investigate, a recipe for each claim type, and the answer format. Nothing in it comes from telemetry.
- the incident context (`context_message`, `:172`): tenant, services in scope, window, incident service
  and first anomaly, as structured fields.

Tools are described by `TOOL_DOCS` (`:137`) and offered through `tool_specs` (`:161`).

## 3. The tool loop

Each turn, `_ask` (`:442`) checks the wall time and tokens, calls the model with at most the wall time
left as its timeout, and counts tokens. If the model asks for tools, each call goes through the same
scope-checked tool layer the baseline uses (`call(...)`, `:498`), so the agent's calls are clamped,
row-capped, snapshotted and stored with `ranker = agent`, exactly like the baseline's.

In this investigation the agent made 10 calls (#25–#34): the timeline, inventory's deploys, inventory's
latency metric twice, inventory's logs (all, then `contains="QueuePool"`), the gateway's timeline,
gateway traces after and before the onset, and the timeline again.

Each result is rendered by `render_result` (`:243`):
- it is wrapped in a boundary made fresh for that call, `<<DATA-{16 hex}>>` … `<</DATA-…>>`
  (`new_boundary`, `:183`), and the prompt says text inside is data, never instructions. A planted log
  line cannot guess the boundary to close it early.
- it is numbered with the agent's own call number, 1..n (`mine`, `:479`, A39). The agent can cite only
  these numbers, so it can only cite its own calls.
- a rejected call carries a hint naming the tool's required arguments, the window and the scope
  (`_rejection_hint`, `:263`); a truncated one says it cannot support a log claim (A42).

When the conversation grows past 10,000 characters, `_compact` (`:429`) reduces older results to their
header line; their rows remain citable, because citations resolve against the stored snapshot, not the
prompt.

When the 20-call budget is used up, the agent gets one answer-only turn (`:504`); asking for tools again
there degrades the run (`budget`).

## 4. The answer, parsed strictly

When the model stops asking for tools, its reply must be exactly the §8.1 JSON object. `parse_output`
(`:306`) checks it field by field (closed kinds, roles, claim types, numbers). An unusable reply gets
one retry constrained to `ANSWER_SCHEMA` (`:284`); a second failure degrades (`parse`) (`:510`–`:523`).

Citations are resolved with `resolve_cites` (`:373`): the agent's numbers become tool-call sequence
numbers; `"rows": "all"` becomes the rows of that call that the claim type can use.

## 5. One repair turn, then the verifier decides

Before returning, the agent runs the verifier itself (`_rejections`, `:542`). If any hypothesis fails,
the verifier's reasons are sent back verbatim and the agent may make more calls and answer once more
(`:530`–`:536`, A39). This investigation used that turn (`"repairs": 1`): it answered twice, the
second time after its timeline call #34.

Its final answer: inventory / bad_deploy, candidate root cause, with two claims:
- `deploy_precedes_onset`: deploy `aa53a621…` of inventory before the onset at 22:42:47;
- `metric_change`: inventory's `http.server.request.duration.mean` up by at least 0.5.

`run_ranker` (`investigation/run.py:29`) hands each hypothesis to `verify` (`investigation/verifier.py:249`),
the same deterministic verifier the baseline faces:
- every cited call must belong to the agent (`verifier.py:88`): a citation of baseline call #4, which
  holds the same deploy row, would be rejected;
- the cause service must be in scope and have a non-runbook claim about it (`:265`, A36);
- each claim is recomputed from the cited snapshot rows (`verify_claim`, `:221`).

Both claims passed, so the agent's hypothesis is stored as `passed` with `ranker = agent`
(`orchestrator.py:200`). The shown result is the agent's (`:203`): outcome ROOT_CAUSE_IDENTIFIED,
status `complete`.

## 6. If the model fails

If the model is unreachable, the reply is unusable twice, or the budget runs out, the agent raises
`Degraded` and the investigation ends `degraded_baseline`, showing the baseline's verified answer, with
every row already committed kept (`orchestrator.py:197`). `tools/kill_llm_demo.py` shows this by killing
Ollama mid-investigation (`docs/measurements/phase3/kill-ollama-demo.txt`).

## 7. Recording and replay

Every request is reduced to a canonical form (`canonical_request`, `investigation/llm.py:68`) and hashed
with the model, its digest and the run index (`request_hash`, `:81`). The data boundaries are replaced by
a placeholder before hashing (`:82`, A35), so a replay matches although the boundaries are random.

`Recorded.complete` (`:286`) answers from the cassette when the key is there (`:292`); in replay mode a
missing key raises `ReplayMiss` (`:295`) instead of calling a model or returning another request's
answer. Cassettes live in `evals/cassettes/gemini-3.5-flash-lite-frozen/`; CI's `agent-replay` job
replays all 35 fixtures from them with no key and no model.

`rca eval` refuses a live agent run on test fixtures unless HEAD carries the `agent-frozen` tag
(`investigation/cli.py:125`).

Because this investigation was replayed (A43), `rca show` prints replay times (46 ms per turn); the
model's recorded time for it was 131 s (`docs/measurements/phase3/test/latency.json`).
