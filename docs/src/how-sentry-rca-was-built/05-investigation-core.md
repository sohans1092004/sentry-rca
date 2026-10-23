
## 5. The investigation core: tools, evidence, verifier, baseline

> **The server decides what may be read; every result is stored before anyone sees it; a claim is accepted only if the verifier can recompute it from the rows it cites. The baseline is a fixed heuristic held to the same verifier as the model.**

### 5.1 Tools and scope

- **The tools are read-only by construction:** `query_metrics`, `query_logs`, `query_traces`, `get_recent_deploys`, `get_incident_timeline` and `search_runbooks`. There is no tool that changes anything (§5.1).
- **`prepare` turns a request into what may run** ([[tools#def prepare(]]):
  - A tenant argument is rejected: the tenant comes from the investigation ([[tools#TENANT_ARGS = ]]).
  - A service outside the scope is rejected and logged.
  - The window is clamped to the investigation's window, and rows are capped at 500 and 256 KiB ([[snapshots#MAX_BYTES = ]]).
  - A rejection is recorded with its reason. It is never silently rewritten (§5.2, ADR-008).
- **Log bodies are untrusted.** Control characters are stripped and bodies are truncated to 500 characters before they are stored or shown ([[tools#_CONTROL = ]]).
- **Snapshots** are content-addressed: the sha256 of the canonical JSON rows, stored zstd-compressed before the result is returned ([[snapshots#def build(]], ADR-012). A claim cites rows of a snapshot, not a live query, so it can be re-checked later against exactly what the ranker saw.
- **Two backends, one answer.** Every tool call of every eval investigation is re-run on a Parquet backend over the same dataset. Its snapshot must be byte-identical to ClickHouse's (A26). The first run found one edge count of 5,717 against 5,718, from ClickHouse's approximate `uniq`; it was fixed with exact counts in both (A33).

### 5.2 The timeline

`get_incident_timeline` returns call edges, deploys and **anomaly onsets** per service and signal: latency, error rate, CPU, memory, pool wait. An onset is the first of two consecutive ticks above median + max(4·1.4826·MAD, 0.5·|median|, a per-signal floor), measured against the first 10 minutes of the window ([[timeline#def onset(]], A20). Bucketing into 30 s first stamped onsets up to 30 s *before* the fault, and made a true deploy-before-onset claim fail on bad_deploy_001. Hence the services' own 5 s ticks.

### 5.3 The verifier

`verify` checks a hypothesis in two layers ([[verifier#def verify(]]). The thresholds are pinned so that the gold-claim generator and the verifier compute identically (A11).

**Every citation** ([[verifier#def _cited(..return out, rows, context]]):
- cites at least one tool call of *this* investigation, made by *this hypothesis's ranker* (A15);
- that call was not rejected and has a snapshot;
- that call is a tool this claim type may cite (A18);
- every cited row is in that snapshot.

**Per claim type:**

| Claim | Recomputed from the cited rows |
|---|---|
| `metric_change` | rows of the claimed service and metric, inside the window plus the 15 minutes before it; at least 3 points on each side; the mean rose (or fell) by at least `min_magnitude` ([[verifier#def _metric_change(]]) |
| `log_pattern` | at least `min_count` cited lines contain the pattern; the cited queries cover the window *and* the equal-length window before it, untruncated; matches in the window ÷ matches before ≥ `min_ratio` ≥ 2 ([[verifier#def _log_pattern(]], A24) |
| `trace_dependency` | in every claimed trace, a cited child span descends from a cited parent span and holds at least `min_latency_share` of its time ([[verifier#def _trace_dependency(]]) |
| `deploy_precedes_onset` | the deploy is the claimed service's, finished before the onset and at most 30 minutes before it, and a cited onset of that service lies within 1 minute of the claimed onset ([[verifier#def _deploy_precedes_onset(]]) |
| `runbook_match` | the cited document's similarity is at least the claimed one and at least 0.75, and it is not the evaluated fixture's postmortem, or one of the same scenario ([[verifier#def _runbook_match(]], A25) |

**The hypothesis as a whole:**
- a known role, and a cause kind from the closed list ([[kinds#CAUSE_KINDS]], A23);
- a root cause needs evidence beyond a similar past incident;
- a root cause's service must be in scope, and at least one non-runbook claim must be *about that service* (A36).

The last rule was added in Phase 3. Without it, true evidence about inventory could have verified a hypothesis naming `dns`, which is exactly what a planted instruction would ask for.

**Tests and guards.**
- An adversarial suite and property tests generate cases that must pass and tightened ones that must fail (`tests/unit/test_verifier.py`, `tests/unit/test_verifier_properties.py`).
- No gold claim was rejected in any eval: 0 of 54 on dev, 0 of 41 on test (`docs/measurements/phase2_5.md`, Q3).
- Removing a check makes a fabricated claim pass: the `verifier_*` guard checks in `tools/guards_phase2.py`.

### 5.4 The baseline ranker

The baseline is a fixed heuristic with no model ([[baseline#def rank(]], ADR-006):
1. **Timeline:** anomaly onsets ordered in time.
2. **Fixed follow-ups** for each anomalous service: deploys, WARN and ERROR logs, the series behind its onsets.
3. **Slow and failing traces:** from the incident service's root span, it walks to the child holding the most time while that child holds at least half the root's. The service reached is that trace's *dominant* service.
4. **A candidate root cause needs a kind-specific signal:** one of three log rules ([[baseline#PATTERNS = ]]), memory growth, or a deploy finishing up to 30 minutes before its onset. A log pattern counts only if it at least doubled against the window before (A24). A service that is only slow is a downstream symptom.
5. **Score:** 0.4 trace dominance + 0.3 kind evidence + 0.2 temporal rank + 0.1 deploy proximity.

Its known blind spots were measured, not tuned away (A32):
- **Ambiguous pairs:** trace dominance favours whichever fault holds the slow traces, so two equal causes rarely land within the 0.1 conflict margin. It got 0 of 3 test pairs right.
- **noisy_neighbor:** a harmless confounder deploy can be blamed.
- **The four test-only kinds:** it has no log rule for them, so it is judged on the service only (A23).

It was frozen as `baseline-frozen` before test was first run, with its sha256 in `evals/accepted.json`; any later change blocks the gate until a post-hoc amendment is logged (A27).

### 5.5 Outcome rules

`decide` looks only at verified root-cause candidates, sorted by score ([[outcome#def decide(]]):
- none → INSUFFICIENT_EVIDENCE;
- a different cause within 0.1 of the top → CONFLICTING_EVIDENCE;
- otherwise → ROOT_CAUSE_IDENTIFIED.

The same rules apply to both rankers, so a ranker cannot talk its way into an outcome.
