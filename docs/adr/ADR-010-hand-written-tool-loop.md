# ADR-010: A hand-written tool loop instead of an agent framework

**Status:** Accepted (Phase 3). Measurements are in `docs/measurements/phase3.md`.

## Context

The agent (SPEC §7.4) chooses tool calls and proposes ranked hypotheses. Everything around the model
is a safety boundary:

- the scope check sits in the Tool-Execution Layer;
- untrusted telemetry must stay inside data blocks;
- the output must match the §8.1 schema;
- the budget must hold even when the model loops;
- every exchange must be recorded so CI can replay it.

The loop that connects these is small. What matters is that each of these properties is visible and
testable at a single place in the code.

## Options

1. **An agent framework** (LangChain/LangGraph, LlamaIndex agents, an SDK's tool runner). It brings
   tool-call parsing, retries, memory and tracing. But its prompt assembly, retry policy and message
   history are the framework's. Placing tool results inside per-call random-boundary blocks, and
   proving nothing else reaches the prompt, would mean working against its abstractions. Its version
   upgrades would also change the requests, which breaks replay keys silently.
2. **A hand-written loop** over the provider interface `complete(messages, tools, temperature=0)`.

## Decision

Option 2: `investigation/agent.py`, about 200 lines of logic.

- **Prompt:** the system message is fixed. The incident context is a JSON block of server-provided
  fields. Each tool result is rendered by `render_result`, which writes a server-authored header and
  then the rows, only between `<<DATA-x>>` and `<</DATA-x>>` with a fresh random `x` per call.
- **Loop:** `Agent._loop`.
  - It asks the model and executes each requested tool through `ToolLayer.call` with ranker `agent`,
    so scope is enforced there and the calls are the agent's own.
  - It stops when the model replies without tool calls.
  - When the tool calls run out, it offers one turn without tools (A37).
- **Budget:** `Agent._ask` checks wall time and tokens before and after every model call. The
  tool-call count is checked before each execution.
- **Output:** `parse_output` is strict. `resolve_cites` maps row numbers to `row_id`s. Then the
  unchanged verifier decides.
- **Failure:** `Degraded` (model unavailable after retries, unusable output after one retry, budget)
  is caught by the orchestrator, which shows the baseline (`degraded_baseline`). A replay miss is not
  caught.

Each property has a remove-the-guard check (`tools/guards_phase3.py`) whose test fails by showing
the unsafe behaviour.

## Consequences

- There is no framework dependency and nothing silently changes the prompt. The request is exactly
  what the code builds, so the replay key (A35) is stable across machines and CI.
- No streaming, no parallel tool calls and no conversation memory beyond one investigation, and none
  is needed: an investigation is one bounded conversation.
- Tool-calling quirks of small models (tool calls written as text, fenced JSON) are not papered over
  by a framework's lenient parser. They show up as measured parse failures, and any leniency added
  later is a logged, dev-measured prompt or parser change.
- **When it would flip:** if the agent grows multi-agent delegation, long-term memory or many more
  tools, a framework's orchestration would earn its weight. The boundary rules above would then have
  to be re-proved inside it.
