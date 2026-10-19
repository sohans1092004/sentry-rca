title: Postmortem: slow query incident (slow_query_001)
kind: postmortem
fixture_id: slow_query_001
---
Incident on gateway opened 2026-10-18 22:29:22.549809+00:00 (15 s after the fault began).
Root cause: a database query in inventory slowed down (reserve, about 546 ms per call).
Symptoms: payments, orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
