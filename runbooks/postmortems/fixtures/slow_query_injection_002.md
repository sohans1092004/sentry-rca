title: Postmortem: slow query incident (slow_query_injection_002)
kind: postmortem
fixture_id: slow_query_injection_002
---
Incident on gateway opened 2026-10-19 02:22:31.945900+00:00 (15 s after the fault began).
Root cause: a database query in inventory slowed down (confirm_hold, about 344 ms per call).
Symptoms: payments, orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
