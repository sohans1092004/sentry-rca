title: Postmortem: dependency outage incident (dependency_outage_ambiguous_001)
kind: postmortem
fixture_id: dependency_outage_ambiguous_001
---
Incident on gateway opened 2026-10-19 04:48:29.070679+00:00 (19 s after the fault began).
Root cause: the external payment provider failed or timed out for most calls from payments.
A second, overlapping cause was also present: inventory (memory_leak).
Symptoms: gateway, orders slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
