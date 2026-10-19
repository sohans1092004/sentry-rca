title: Postmortem: slow query incident (slow_query_ambiguous_001)
kind: postmortem
fixture_id: slow_query_ambiguous_001
---
Incident on gateway opened 2026-10-18 23:55:07.285891+00:00 (16 s after the fault began).
Root cause: a database query in orders slowed down (insert_order, about 299 ms per call).
A second, overlapping cause was also present: inventory (bad_deploy).
Symptoms: gateway, payments slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
