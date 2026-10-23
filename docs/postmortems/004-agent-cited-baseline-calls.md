# Incident 004: the agent cited the baseline's tool calls, and the verifier rejected every one

**Date:** 2026-10-21 · **Type:** agent defect, caught by a safety check · **Found by:** dev model selection (qwen2.5:3b and llama3.2:3b, N=1, 19 fixtures) · **Status:** resolved (A39)

## Summary

In one investigation the baseline runs first and makes about 15-25 tool calls (sequence numbers 1..k). The agent's calls continued the same numbering (k+1..). The model was asked to cite tool calls by number.

Small models cited low numbers, the first calls in a list, as if their own calls started at 1. Those numbers belonged to the baseline.

The verifier's same-ranker rule (A15) rejects any agent hypothesis that cites a call the agent did not make. **It rejected every such claim**, so no wrong evidence reached a person. But it also meant the agent could not verify anything, even when it had found the right evidence itself.

## Impact

Dev model selection (A39):
- **0 of 48 agent hypotheses verified** across both models;
- **10 of the failed claims cited a baseline call number** (8 qwen2.5:3b, 2 llama3.2:3b);
- **30 claims cited `"all"` rows that selected nothing**, a related numbering confusion;
- **one qwen2.5:3b run took 1,041 s against a 600 s wall budget.** That was a separate gap found in the same pass: the budget was checked only between model calls.

## Root cause

**The model was handed the system's numbering instead of its own.** Tool-call sequence numbers are unique per investigation (A15) because the audit trail is one table. That is right for the audit, and wrong as an interface for a model that only sees its own calls.

**The safety check worked, which hid the defect.** Nothing unsafe happened, so the failure showed up only as a low verification rate, not as an error.

## Fix (A39, commit `65a51ad`)

- **The agent numbers its own calls 1, 2, … and cites those numbers.** The loop maps them to the stored sequence numbers. A number that is not one of the agent's calls becomes `-n`, which no investigation has, so the verifier rejects it, and doesn't silently pick the wrong call.
- **`"all"` that selects no rows becomes a placeholder row** that the verifier reports, instead of an empty citation.
- **One repair turn:** if any hypothesis is rejected, the agent gets the verifier's reasons verbatim and may query and answer once more. The verifier still decides.
- **Each model call gets at most the wall time left.** A timeout there is the budget, not a retry.
- **The same-ranker check was not changed.** It remains the guarantee; the numbering only makes it possible for the agent to pass it honestly.

## Verification

- `test_agent_tool_calls_are_its_own_and_its_claims_verify`: the agent's claims cite its own calls and verify.
- `test_row_numbers_resolve_to_the_snapshot_row_ids_and_bad_ones_are_kept_for_the_verifier`: bad numbers stay bad, for the verifier to reject.
- `test_a_hypothesis_citing_the_baseline_rankers_call_is_rejected`, with the guard check `same_ranker_citations`: with the same-ranker check removed, an agent hypothesis citing a baseline call is accepted, and the test fails.
- `test_each_model_call_gets_only_the_wall_time_left_and_a_timeout_there_is_the_budget`.
- **After the fix,** later dev runs had no baseline-call citations among their rejection reasons:
  - hosted model, before iteration C: 5 of 10 agent hypotheses verified;
  - frozen agent on test: 4 of 6 verified (`docs/report-phase3.md`).

## Notes

- **Did not happen:** a wrong citation reaching a person. The defence in depth held. The cost was evaluation signal: a whole selection pass in which no model could verify anything.
- **Not shown by this fix:** that small local models can do the job. After A39 and A40, local qwen2.5:3b still verified 0 of 9 hypotheses on dev. The evaluated agent moved to a hosted free-tier model (A41).
