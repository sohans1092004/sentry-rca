# ADR-007: Typed claims checked by a deterministic verifier

**Status:** Accepted (Phase 2). Numbers from the Phase 2 eval go in `docs/measurements/phase2.md`.

## Context

An investigation's output is a set of hypotheses. A hypothesis that merely *mentions* a tool result
proves nothing: v1 of the spec accepted any hypothesis that cited a real tool call, so any query
result could support any sentence. Phase 3 adds an LLM, whose text can be fluent and wrong.

## Options

1. **Citation-existence check** (v1): the cited tool call exists. Cheap, and verifies nothing.
2. **LLM judge**: a second model rates whether the evidence supports the claim. Non-deterministic,
   itself persuadable by the same injected text, and not reproducible in CI.
3. **Typed claims and a deterministic verifier**: every hypothesis is a list of claims of five types
   (`metric_change`, `log_pattern`, `trace_dependency`, `deploy_precedes_onset`, `runbook_match`),
   each with explicit parameters and citations to specific rows of specific tool calls. Code checks
   each claim against the cited rows.

## Decision

Option 3 (SPEC §8, numeric rules A11, refinements A15/A18). `investigation/verifier.py`:

- reads only the cited tool calls' snapshots, never live telemetry, and calls no tool and no model;
- runs the common checks (the call exists in this investigation, belongs to the hypothesis's ranker,
  was not rejected, has a snapshot, is the right tool for the claim type; every cited row is in the
  snapshot, from the claim's service, inside its window), then the claim-type check;
- rejects a hypothesis on its first failed claim and stores every claim's result and reason;
- requires a root-cause hypothesis to carry evidence beyond `runbook_match`.

Each check is one `_require(condition, reason)`, so each is tested, and guard-checked, on its own.

## Consequences

- **What it guarantees:** a passed claim is arithmetically true of rows the system actually
  returned, under exactly the rules in §8.2/A11. Fixture gold claims (built independently in
  `recorder/gold.py`, which the verifier never imports) pass with zero false negatives, and on
  generated variants the two agree (property tests).
- **What it does not guarantee:** that the claims add up to the right *cause*. A hypothesis can be
  fully verified and still be ranked wrong; accuracy is measured by the eval, not by the verifier.
  Narrative text is never verified and is shown as "unverified explanation".
- **Expressiveness is the price:** a cause the five claim types cannot describe cannot be verified.
  New claim types need a spec amendment, a check, adversarial tests and a guard.
- Rejected hypotheses are stored for audit (append-only), never shown as live results.
