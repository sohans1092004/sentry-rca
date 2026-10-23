
## 9. Testing, guards and CI

> **Every safety property has a test, and every such test was watched failing with its guard removed, by showing the unsafe behaviour, not just by erroring.**

### 9.1 What runs

| Suite | Count | What it covers |
|---|---|---|
| unit | 189 | rules, verifier (adversarial and property-based), agent loop with fake models, recorder, injector, leak test, secret scan |
| integration | 33 | Testcontainers: real ClickHouse, Postgres and Redpanda; commit-after-insert, dedup, the alert engine, orchestrator crash points, degradation |
| fixtures | per dataset | content hashes match the manifest; labels are well-formed; every gold claim verifies; out-of-scope evidence is rejected by scope; the baseline is byte-identical across runs |
| viewer | 4 | headless Chromium: script payloads in every recorded field never execute or become markup; the CSP blocks inline script |
| baseline eval | 35 fixtures, N=5 | the §12.5 gate: no gold claim rejected, no out-of-scope citation allowed, no backend mismatch, a frozen baseline |
| agent replay | 35 fixtures, N=1 | the frozen agent from its cassettes, no key and no model; a replay miss fails the job |

CI runs all of these on every pull request (`.github/workflows/ci.yml`). The `pages` job deploys the viewer from the agent-replay job's export, and only from `main`.

### 9.2 Remove-the-guard checks

`tools/guard_checks.py` takes each guard, applies an edit that removes it, and runs the guard's tests, which must fail. It then restores the guard and runs them again, and they must pass ([[guards#def check(name: str)]]). The output keeps the failing assertion, so the record shows the unsafe behaviour: a cross-tenant row returned, a fabricated claim passing, a duplicate incident, a looping agent running past its budget, a replay calling a live model, telemetry parsed into page markup (`tools/guard_checks.out`).

All 69 pass (full run 15:35-15:53 UTC, 23 Oct; `tools/guard_checks.out`). There are 67 guards before Phase 4 (8 Phase 1, 33 Phase 2, 15 Phase 2.5, 11 Phase 3) and 2 in Phase 4 ([[guards4#GUARDS_PHASE4]]):
- `viewer_text_only`: with text rendering replaced by HTML parsing, the XSS test reports elements parsed from telemetry, and CSP violations.
- `viewer_csp`: with the CSP meta tag removed, an inline script runs.

### 9.3 Failure scenarios exercised

| Scenario | Result | Source |
|---|---|---|
| Redpanda down 60 s | queued and drained, no gap, no restart **[laptop]** | `docs/measurements/phase1.md`, M4 |
| Processor killed between insert and commit | redelivered batch deduplicated by stable IDs | integration test, guard `commit_after_insert` |
| Model killed mid-investigation | `degraded_baseline`, baseline answer shown, nothing lost **[laptop]** | `docs/measurements/phase3/kill-ollama-demo.txt` |
| Malformed model output | one schema-constrained retry, then `degraded_baseline` | `test_malformed_output_gets_one_retry_then_degrades` |
| Overnight memory pressure | three spurious incidents stalled recording 84 min; causes found (an archiver crash loop, dev runs, OneDrive sync) and fixed; no fixture contaminated, because the recorder waits for quiet | `docs/measurements/phase1.md`, M6 |
| Telemetry spike during an investigation | **not run** (deferred, A44) | |
