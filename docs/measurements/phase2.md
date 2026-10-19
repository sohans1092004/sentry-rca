# Phase 2 measurements

Every number below comes from the command shown and its recorded output (`runs/` holds the raw JSON
locally; the summary is also stored in Postgres `eval_runs`/`eval_results`).

Laptop: Windows 11, 20 logical CPUs, 15.6 GB RAM; Docker Desktop 4.92.0, WSL2 VM 7.75 GB. Fixtures:
Release `fixtures-v2` (19 datasets, labels with in-scope gold claims, A14/A19).

## P1. Baseline eval, all 19 fixtures, N = 5 (SPEC ง12.3, A16)

```
$ uv run rca eval --n 5 --accept --out runs/eval-phase2.json
eval_run_id af957445-30a8-4bf4-b092-834b3ca9da5b  git 7fb7ac45dccecbda8a7233c3aca9f93d28a8eead
{
  "fixtures": 19,
  "n_runs": 5,
  "top1": {
    "mean": 1,
    "stdev": 0.0,
    "min": 1,
    "max": 1
  },
  "top3": {
    "mean": 1,
    "stdev": 0.0,
    "min": 1,
    "max": 1
  },
  "confusion": {
    "ROOT_CAUSE_IDENTIFIED": {
      "ROOT_CAUSE_IDENTIFIED": 55,
      "INSUFFICIENT_EVIDENCE": 0,
      "CONFLICTING_EVIDENCE": 0
    },
    "INSUFFICIENT_EVIDENCE": {
      "ROOT_CAUSE_IDENTIFIED": 0,
      "INSUFFICIENT_EVIDENCE": 25,
      "CONFLICTING_EVIDENCE": 0
    },
    "CONFLICTING_EVIDENCE": {
      "ROOT_CAUSE_IDENTIFIED": 10,
      "INSUFFICIENT_EVIDENCE": 0,
      "CONFLICTING_EVIDENCE": 5
    }
  },
  "gold_claims": 58,
  "gold_rejected": 0,
  "out_of_scope_evidence": 2,
  "out_of_scope_allowed": 0,
  "injection_influence": 0
}
gate: PASS
```

Wall time 06:01:44 -> 06:10:23 UTC (8 min 39 s, loading included).

| Fixture | Expected | Actual (5 runs) | Rank-1 verified root cause | Top-1 | Top-3 | Latency to outcome ms (min / median / max) | Tool calls | Injection influenced |
|---|---|---|---|---|---|---|---|---|
| bad_deploy_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | payments:bad_deploy | 5/5 | 5/5 | 1468 / 1593 / 1734 | 16 | - |
| bad_deploy_002 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | orders:bad_deploy | 5/5 | 5/5 | 1250 / 1343 / 1375 | 12 | - |
| bad_deploy_ambiguous_001 | CONFLICTING_EVIDENCE | CONFLICTING_EVIDENCE ื5 | payments:dependency_outage | 5/5 | 5/5 | 2188 / 2516 / 2813 | 21 | - |
| dependency_outage_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | payments:dependency_outage | 5/5 | 5/5 | 1640 / 1655 / 1734 | 16 | - |
| dependency_outage_ambiguous_001 | CONFLICTING_EVIDENCE | ROOT_CAUSE_IDENTIFIED ื5 | payments:dependency_outage | 5/5 | 5/5 | 2391 / 2703 / 4905 | 22 | - |
| dependency_outage_injection_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | payments:dependency_outage | 5/5 | 5/5 | 1687 / 1766 / 1797 | 16 | 0/5 |
| memory_leak_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | payments:memory_leak | 5/5 | 5/5 | 1531 / 1625 / 1686 | 17 | - |
| no_fault_001 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE ื5 | none | 5/5 | 5/5 | 1797 / 1842 / 1844 | 19 | - |
| no_fault_002 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE ื5 | none | 5/5 | 5/5 | 1843 / 1906 / 2000 | 19 | - |
| no_fault_003 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE ื5 | none | 5/5 | 5/5 | 1844 / 1875 / 1952 | 19 | - |
| noisy_neighbor_001 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE ื5 | none | 5/5 | 5/5 | 1546 / 1563 / 1750 | 15 | - |
| noisy_neighbor_002 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE ื5 | none | 5/5 | 5/5 | 1406 / 1608 / 2766 | 15 | - |
| pool_exhaustion_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | inventory:pool_exhaustion | 5/5 | 5/5 | 2188 / 2250 / 2266 | 21 | - |
| pool_exhaustion_002 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | inventory:pool_exhaustion | 5/5 | 5/5 | 2092 / 2125 / 2344 | 21 | - |
| pool_exhaustion_003 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | inventory:pool_exhaustion | 5/5 | 5/5 | 2297 / 2391 / 2952 | 21 | - |
| slow_query_001 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | inventory:slow_query | 5/5 | 5/5 | 1547 / 1625 / 1671 | 16 | - |
| slow_query_002 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | orders:slow_query | 5/5 | 5/5 | 1484 / 1500 / 1718 | 12 | - |
| slow_query_ambiguous_001 | CONFLICTING_EVIDENCE | ROOT_CAUSE_IDENTIFIED ื5 | orders:slow_query | 5/5 | 5/5 | 2015 / 2094 / 3062 | 21 | - |
| slow_query_injection_002 | ROOT_CAUSE_IDENTIFIED | ROOT_CAUSE_IDENTIFIED ื5 | inventory:slow_query | 5/5 | 5/5 | 1936 / 2235 / 2438 | 20 | 0/5 |

Verifier results by claim type over all 95 investigations:

| Claim type | Passed | Failed |
|---|---|---|
| deploy_precedes_onset | 20 | 0 |
| log_pattern | 55 | 0 |
| metric_change | 320 | 0 |
| runbook_match | 70 | 0 |
| trace_dependency | 185 | 0 |

How to read this, honestly:

- **Spread is 0**: the baseline is deterministic (byte-identical hypotheses across runs, tested), so
  the five runs per fixture agree exactly; N = 5 measures nothing for it, and will for the agent.
- **Top-1 = 1.00 is optimistic.** The baseline's kind rules match log lines the same author wrote into
  the fault injector ("pool acquire timeout", "slow query", "provider charge failed"), and top-1
  counts an ambiguous fixture correct when rank 1 is either acceptable cause. The outcome accuracy is
  the stricter number: **80 of 95 runs (84 %)**.
- **The two misses are both ambiguous fixtures** (`dependency_outage_ambiguous_001`,
  `slow_query_ambiguous_001`): both injected causes are found and verified, but scored more than the
  0.1 conflict margin apart, because one cause dominates the slow traces and the other (an error-mode
  or briefer fault) barely shows in them. Reported as measured; the weights were not tuned to the labels.
- **No victim blamed**: both `noisy_neighbor` fixtures end `INSUFFICIENT_EVIDENCE` in every run (ADR-006).
- **Rejection rate 0 %** for the baseline is by construction: it claims only what its cited rows show,
  with thresholds below the observed values. The verifier's rejections are exercised by the adversarial
  suite (29 tests) and the property tests, not by this ranker.
- **Investigation latency** (trigger to recorded outcome, the baseline computes all hypotheses before
  verifying, so first verified hypothesis = outcome): 1.25-4.9 s per investigation, under the ยง1.2
  60 s / 90 s targets by an order of magnitude.

## P2. Verifier / gold agreement

```
$ uv run rca eval --n 5 ...          (gold replay inside each fixture's eval investigation)
gold_claims 58, gold_rejected 0       -> verifier false-negative rate 0 (SPEC ยง1.4)
out_of_scope_evidence 2, allowed 0    -> both batch-job claims rejected by scope (A14)

$ uv run pytest tests/unit/test_verifier_properties.py
3 passed  (metric_change: 400 generated cases agree with recorder/gold.check_metric_change;
           log_pattern: 300, trace_dependency: 200 โ€” gold's claims pass, tightened ones fail)
```

No disagreement between the verifier and `recorder/gold.py` was found; none had to be resolved.

## P3. Contamination (SPEC ยง12.2) in practice

```
$ psql: runbook_match claims of eval af957445..., by cited document
 kind       | fixture_postmortem | own_postmortem | count
 postmortem | t                  | f              |    55
 runbook    | f                  |                |    15
```

The rule holds (no fixture's own postmortem is ever cited), but 55 of 70 `runbook_match` claims cite a
*sibling* fixture's postmortem (e.g. `pool_exhaustion_002`'s while evaluating `pool_exhaustion_001`),
which describes the same injected failure. Harmless for the baseline (runbook evidence is supporting
only, never a root cause on its own), but a shortcut an LLM agent could exploit. Proposed, not applied:
exclude every postmortem of the same scenario while a fixture is evaluated.

## P4. Guard checks (remove-the-guard), all 41

```
$ uv run python tools/guard_checks.py          06:11:11 -> 06:22:51 UTC
41 PASS, 0 FAIL   (8 Phase 1 + 33 Phase 2; full output in tools/guard_checks.out)
```

Each guard's test fails with the guard removed by showing the unsafe state (a cross-tenant row
returned, an out-of-scope service queried, a fabricated claim passing, a duplicate investigation row,
an UPDATE succeeding on an audit table, a written eval DB passing the hash) and passes restored.

## P5. Memory at the end of Phase 2 (orchestrator running, `deploy-*` running)

```
$ bash tools/memory.sh "phase2-end, orchestrator running"     2026-10-19T06:23:07Z
TOTAL 1814.6 MiB (17 containers)     clickhouse 658.4, redpanda 388.5, otel-collector 126.3,
                                     orchestrator 56.0, postgres (pgvector) 53.5, others < 56 each
Docker VM: total 7751, used 4042, available 3422 MiB     host free 2,028 of 16,004 MiB
```

Phase 2 adds the orchestrator (56 MiB); the pgvector Postgres image is the same size as Alpine at this
data volume. Stack total 1.81 GB vs 1.65-1.80 GB in Phase 1 (M6), within the 5 GB budget. Ollama
(nomic-embed-text, 274 MB on disk) runs on the host only to record or re-verify the embedding cassette;
investigations and evals read the cassette and do not need it.
