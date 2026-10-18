# ADR-004: Rule-based and statistical alerting, not ML anomaly detection

**Status:** Draft (Phase 1). Per-scenario latencies are in `docs/measurements/phase1.md`.

## Context

The Alert Engine opens the incidents that everything downstream investigates and that every fixture
is built around. Its decisions must be reproducible (the same telemetry → the same incident),
explainable to an on-call engineer in one sentence, and cheap. An incident that cannot be explained
cannot be a ground-truth label.

## Decision

Rules live in `alert_rules` (SPEC §4.2) and are evaluated every 5 s over ClickHouse (`alerting/`):

- **Static threshold:** gateway 5xx rate > 5 % over 60 s with ≥ 20 requests.
- **Rolling statistic:** gateway p95 latency (from histogram buckets, as Prometheus'
  `histogram_quantile` does) as a robust z-score: median and MAD of 1-minute p95s over the trailing
  30 min; fire when z > 4 **and** p95 > 1.5 × median **and** p95 − median > 20 ms.
- Two consecutive breaching evaluations open or update an incident; 3 min without a breach
  resolves it (Amendment A8).
- **Edge SLO only** (Amendment A1): one composite rule on `gateway`. One failure → one fingerprint →
  one incident. The investigation, not the alert, says which service caused it.

No LLM and no learned model anywhere in this path.

## Why these choices

- **Median/MAD, not mean/std.** A previous incident inside the trailing 30 minutes inflates a mean
  and a standard deviation and masks the next incident; up to half the baseline minutes can be bad
  before the median moves.
- **Ratio and absolute floors.** On a flat baseline, MAD is near zero and a 2 ms wobble is z = 10.
  The 1.5× and +20 ms floors, plus sigma floored at 5 % of the median, stop that (unit test
  `test_latency_fires_only_with_baseline_and_all_floors`).
- **Edge, not per-service.** Per-service rules would open 3–4 incidents for one multi-hop failure,
  each with its own fingerprint, and point the alert at the cause, which pre-empts the
  investigation being evaluated.

## Consequences

- Deterministic and testable as pure functions (`alerting/rules.py`, `tests/unit/test_rules.py`).
- **Blind spots, measured not hidden:** failures that never reach the gateway's latency or error rate
  (a batch job slowing only itself) do not alert. Slow-onset faults (memory_leak) alert later than step
  faults. TODO: per-scenario alert-to-incident latency table, filled from the fixture campaign.
- Dedup comes from the database, not the engine: the `incidents_one_open` partial unique index plus
  `ON CONFLICT ... DO UPDATE` (guard check `incidents_one_open`).
- Thresholds are defaults to confirm after the first baseline eval (SPEC §19.3).

## When this would flip

Many services and metrics with seasonal baselines where hand-set rules stop scaling: then a learned
detector *proposing* rules that are still evaluated deterministically, so incidents stay explainable.
