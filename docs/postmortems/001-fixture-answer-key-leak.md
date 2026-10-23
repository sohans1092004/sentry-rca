# Incident 001: the fixtures carried the answer key, so the baseline scored 1.00

**Date:** 2026-10-19 (found) to 2026-10-21 (closed) · **Type:** evaluation validity · **Found by:** the Phase 2 baseline eval (`af957445`, commit `7fb7ac4`) and, later, the leak test · **Status:** resolved

## Summary

The Phase 2 baseline eval scored a perfect top-1 accuracy of 1.00 over 19 fixtures and 5 runs each (`docs/measurements/phase2.md`, P1). That number did not measure investigation. The injector made the demo services emit text that only a fault produced, and that text named the fault. The baseline's kind rules then read that text.

There were three leaks, found in turn:
1. **Fault-only messages.** A pool exhaustion logged `pool acquire timeout`, a slow query logged `slow query … took over`, and a bad deploy logged `KeyError 'currency' (version …)`. None of these appeared in healthy traffic.
2. **A source attribute.** Every injected line was logged from the fault module, so OpenTelemetry stamped it with `code.file.path = …/faults.py`.
3. **An HTTP span.** After the first two were fixed, the injector still started noisy_neighbor's CPU job with an HTTP call to `batchjob`. That left a request span and request metrics that only noisy_neighbor fixtures had.

A fourth shortcut lay in the runbook corpus: 55 of 70 runbook citations pointed at a *sibling* fixture's postmortem, which describes the same fault.

## Impact

| | Phase 2 (v2 fixtures) | After the fix (v3, dev) | v3 test (held out) |
|---|---|---|---|
| Baseline top-1 judged | 1.00 | 0.842 | 0.438 |
| Outcome correct | 80 of 95 runs (84 %) | 65 of 95 (68 %) | 40 of 80 (50 %) |

Sources: `docs/measurements/phase2.md` (P1) and `docs/measurements/phase2_5.md` (Q3).

The leak was in the data, not only in the code. `tools/leak_history.py` counts the leaked strings in the v2 and v3 datasets (`docs/measurements/phase4/leak-history.txt`):

| String or attribute | v2: where it appears | v3 |
|---|---|---|
| `pool acquire timeout` | pool_exhaustion fixtures only (198 lines) | absent |
| `slow query` | slow_query fixtures only (2,164) | absent |
| `KeyError 'currency'` | bad_deploy fixtures only (164) | absent |
| `provider charge failed` | bad_deploy and dependency_outage fixtures only (3,940) | every scenario, including no_fault (148) |
| `deploy finished` | fault deploys only (4) | fault deploys, harmless confounder deploys and no-fault fixtures |
| `code.file.path` = `faults.py` | 325 lines, in bad_deploy, dependency_outage and slow_query fixtures | absent |

No investigation was harmed; the problem was the measurement. A model evaluated on v2 would have looked as good as one that only searched logs for the scenario's name.

## Root cause

**The code that injected a fault also described it.** The fault paths in the demo services logged what they did, in the injector's own words:
- `services/demo_db.py` at `6482a38`, line 70: `pool acquire timeout after %.1fs for query %s (pool size %d)`;
- the same file, line 80: `slow query %s took over %d ms`;
- `services/faults.py` at the same commit, line 94: the bad-deploy error, `unhandled error in %s %s: KeyError 'currency' (version %s)`.

The Phase 2 baseline matched three of those strings to cause kinds (`investigation/baseline.py` at `7fb7ac4`, lines 30-32). Healthy traffic never produced them, so finding the string meant finding the answer.

**The logger was the fault module.** Planted lines, the deploy announcement and the bad-deploy error were all logged by the logger in `services/faults.py`. The OpenTelemetry logging handler records each line's source file, so `code.file.path` was a perfect label for "this line came from the injector".

**The injector touched the system in a way real faults don't.** noisy_neighbor's CPU job was started by `POST /_fault` to `batchjob`. That request is itself telemetry, and only noisy_neighbor fixtures had it (A31).

**The postmortem corpus described the faults.** Each fixture's postmortem was in the runbook corpus. The eval excluded a fixture's own postmortem, but not its siblings' (`docs/measurements/phase2.md`, P3).

## Fix (Phase 2.5, commits `d4f94d1`, `2ae149a`, `e17c0ff`, `73a72a6`)

- **Faults surface only through normal code paths** (A21). A slow query is a real lock wait inside the demo database, so the SQL and spans don't change. Pool exhaustion is a connection leak that logs the pool library's own `QueuePool limit … connection timed out`. A bad deploy raises a real `KeyError` handled by the shared request logger. Planted lines arrive as client input.
- **Healthy traffic speaks the same vocabulary** (A21): database stalls, provider blips, refused connections, config reloads, cache invalidations and malformed requests, all at low rates. A string is no longer evidence; a rise is.
- **Log claims must prove a rise** (A24). A log pattern counts only if it is at least 2x the equal-length window before. The rule is in the verifier and in the gold-claim generator.
- **Confounders in about half the fixtures** (A22): a harmless deploy, a mild unrelated anomaly, and sampling of logs and traces.
- **A held-out test split** (A22, A27) with four scenarios the baseline was never built for. The baseline was frozen as `baseline-frozen` before test was run, and any later change needs a post-hoc amendment.
- **Same-scenario postmortems excluded** from runbook search while a fixture is evaluated (A25). The corpus was rewritten in v3 vocabulary (A34).
- **noisy_neighbor's job starts with `docker exec`** inside the container, not over HTTP (A31).
- **A leak test** (`recorder/leaks.py`, A28) finds markers by measurement, not by reading code. It lists every log template (source file, function, line, severity), attribute, span name and status, metric and deploy-version shape. It fails if one never appears in healthy traffic and appears with only one scenario's faults, or only with confounders. It also checks that the runbook corpus names no injector internals.

## Verification

- **Leak test.** The first run on the 19 dev v3 datasets failed 96 items, all from the `batchjob` HTTP call. That is how the third leak was found. After A31: `uv run python -m recorder.leaks` gives 18,340 items over 35 datasets, 101 never healthy, **0 leaks** (`docs/measurements/phase2_5.md`, Q2). The corpus check finds 0 of 52 documents (A34).
- **The strings are gone, or now shared** (table above).
- **Tests:** `test_markers_are_caught_and_shared_vocabulary_is_not` and `test_corpus_leaks_are_caught`; the guard checks `leak_scenario`, `leak_confounder` and `leak_corpus`.
- **The baseline dropped to honest numbers:** 0.842 on dev and 0.438 on held-out test.

## Notes

- **What a leak test cannot see.** It compares marginal distributions: an item that appears only with one scenario. A combination of individually common items that only one fault produces would pass it. Scenarios are judged by their rise against a pre-window for that reason, not by vocabulary.
- **The lesson.** The 1.00 was suspicious when it was measured, and the Phase 2 write-up called it optimistic. The fix was to make the data honest, not to tune the ranker down. The baseline's weights and thresholds were not changed (A32).
