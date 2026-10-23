# Incident 003: the replay key could never match a recorded request

**Date:** 2026-10-21 · **Type:** spec contradiction, caught before the recorder was written · **Found by:** reading SPEC §7.4 against the Phase 3 build list · **Status:** resolved (A35)

## Summary

SPEC §7.4 asked for two things that couldn't both hold:
- **the prompt-injection mitigation:** every tool result goes to the model inside a delimited block whose boundary is random and new for each call, so a planted log line cannot guess it and close the block early;
- **record and replay:** a response is replayed when sha256(model, digest, canonical request, run index) matches a recorded one, and a miss fails loudly. CI runs replay only.

A random boundary is part of the request, so every request is unique. With the key as specified, **no replay could ever hit**: CI would fail on its first exchange. Or, if the miss were relaxed to save CI, the replay would stop proving anything.

## Impact

None reached a recorded run: it was raised as a question before the recorder existed. Had the key been built as written, two outcomes were possible:
- **every CI run of the agent fails** with a replay miss on its first model call;
- **the tempting quick fix makes replay meaningless.** A fixed boundary, or a key over only part of the request, would replay a response for a request that had changed. A changed tool result would then get the old answer.

## Root cause

Two sections were written for different goals, security and reproducibility, and nobody checked them together. The boundary's randomness is what makes it safe. The key's coverage of the whole request is what makes replay a test.

## Fix (A35; the user chose it among the options raised)

- **The key covers the whole request with each boundary replaced by a fixed placeholder** (`request_hash`, `investigation/llm.py`). Every other byte of the canonical request is hashed: messages, tool schemas, temperature, context and reply limits, and the answer schema. So is the model digest and the run index.
- **The boundary stays random in what the model sees.** A planted line still cannot predict it.
- **A miss raises `ReplayMiss`.** There is no fallback to a live model and no nearest match.
- **One cassette per model and fixture**, with full requests in `llm_exchanges` (append-only for the app role). A cassette recorded with another model digest refuses to load.

## Verification

- `test_record_then_replay_returns_the_recorded_response_and_boundaries_do_not_matter`: the same request with a different boundary replays.
- `test_a_replay_miss_fails_loudly_and_never_calls_a_live_model`: a changed row, another run index or another model digest misses, and the live provider is never called.
- **Guard checks:**
  - `replay_key_whole_request`: with the hash reduced to a constant, a changed request is answered from another request's recording, and the test fails;
  - `replay_miss_loud`: with the miss path removed, the live model is called, and the test fails.
- **In use:**
  - The CI `agent-replay` job replays all 35 fixtures of the frozen agent with no key and no model, and passed on PR #2.
  - A local replay of the same cassettes reproduced every recorded dev and test result (`docs/measurements/phase3/test/replay-check-all.json`, A43).
  - The test run's completion used the same mechanism: 13 fixtures were replayed and checked identical to the interrupted attempt.

## Notes

- **The placeholder rewrites any `DATA-` followed by 16 hex characters**, including one that telemetry happened to contain. That can only make two requests share a key when they differ in nothing but such a token. That is the intended equivalence.
- **Replay proves the loop is deterministic given the model's answers, not that the model is.** The hosted model has no digest. A live re-run may differ (4 of 6 identical dev runs changed their top answer). The cassettes, not a re-run, are the reference.
