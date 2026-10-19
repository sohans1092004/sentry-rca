title: Postmortem: dependency outage incident (dependency_outage_001)
kind: postmortem
fixture_id: dependency_outage_001
---
Incident on gateway opened 2026-10-18 22:50:42.467250+00:00 (12 s after the fault began).
Root cause: the external payment provider failed or timed out for most calls from payments.
Symptoms: orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
