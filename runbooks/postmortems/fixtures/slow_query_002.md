title: Postmortem: slow query incident (slow_query_002)
kind: postmortem
fixture_id: slow_query_002
---
Incident on gateway opened 2026-10-19 05:09:54.029948+00:00 (15 s after the fault began).
Root cause: a database query in orders slowed down (insert_order, about 595 ms per call).
Symptoms: gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
