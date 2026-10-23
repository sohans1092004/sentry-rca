# Incident 002: the previous fault hid the next one from the alert

**Date:** 2026-10-19 (found) to 2026-10-20 (closed) · **Type:** detection gap, found in a smoke run · **Found by:** the Phase 2.5 fault smoke run (`tools/smoke_faults.py`) · **Status:** resolved

## Summary

The edge alert fires on gateway p95 latency when its robust z-score against the previous 30 minutes exceeds 4 (A8). The fixture recorder waited only 15 quiet minutes between faults. So the alert's 30-minute baseline still held the previous fixture's fault.

That fault raised the baseline median and its spread. A new fault's 4x rise in p95 then scored a z of only 1.0-3.8, and **no incident opened**. The detector was comparing the new fault against the old one.

## Impact

- **Smoke run:** cache_stampede and cpu_throttling each raised gateway p95 about 4x. Their baseline median was 179-224 ms, against about 100 ms healthy, with z 1.0-3.8. Neither opened an incident (A29; commit `2ae149a`).
- **A second path, found the next night:** memory_leak_001 (00:25 UTC) raised gateway p95 only 1.43x at the overnight traffic minimum. That is under the alert's 1.5x floor, so it opened no incident and left no incident period to exclude. slow_query_ambiguous_001 was then injected 15 minutes later with the leak inside its 31-minute alert baseline (commit `6b18350`).
- **A fault that does not alert fails its fixture.** The campaign retries failed fixtures in a later pass (commits `3edf7a4`, `dcd2732`). The logs don't record whether the slow_query_ambiguous_001 attempt with the leak in its baseline was kept or retried.

## Root cause

Two windows were set independently and didn't fit together:
- **the alert baseline:** 30 minutes, at least 10 minutes of data (A8);
- **the recorder's quiet gap:** 15 minutes, chosen to keep a 19-fixture campaign near 7 hours (A7).

Nothing stopped a past fault from becoming "normal" for the detector. The robust z-score resists a few outliers, but not a fault that fills a third of its window.

## Fix (A29)

- **The alert baseline excludes incident periods.** Each minute that overlaps one of the rule's incident periods is dropped: from first anomaly to `last_seen` + 3 minutes, or to now for an open incident (`outside_incidents`, `alerting/rules.py`). If fewer than 10 clean minutes remain, the latency condition does not evaluate, and only the error-rate condition can fire.
- **The recorder starts a fault only on a clean baseline.** `wait_quiet` (`recorder/record.py`) waits until no incident is open and none lies in the window plus alert baseline (31 minutes). It also waits until the *last injection* is older than that. This covers a fault that opened no incident.
- **The injector re-checks at the moment the first fault step is applied.** If the check fails, it undoes what was applied and fails the fixture.

## Verification

- **Tests:**
  - `test_baseline_minutes_inside_an_incident_period_are_excluded` and `test_excluding_the_previous_fault_lets_a_new_one_alert` (unit);
  - `test_a_previous_incident_does_not_hide_a_new_fault_in_the_baseline` (the engine on real ClickHouse and Redpanda);
  - `test_fault_start_is_refused_while_an_incident_lies_in_the_alert_baseline` (the recorder).
- **Guard checks:** `alert_baseline_exclusion`, `alert_baseline_wiring` and `recorder_clean_start`. Each fails with its guard removed, by showing a hidden fault or a dirty start.
- **The v3 campaigns:** 35 fixtures recorded with alert latencies of 13.0-26.7 s for fast-onset faults, against a 30 s target (`docs/measurements/phase2_5.md`, Q1). One test fixture, memory_leak_t01, did not alert in 2 of 2 attempts. That was a genuinely weak fault (1.3x at the traffic minimum), not contamination. It was left out, not retuned.

## Notes

- **Cost:** the campaign is slower. Each fault now waits at least 31 minutes after the previous incident instead of 15.
- **A related false alarm had a different cause.** Healthy gateway p95 sat on a histogram bucket edge (0.1 s), so a few slow requests moved the interpolated p95 past the 1.5x ratio. The fix was finer buckets (A30), not a looser rule.
