title: Postmortem: slow query incident (slow_query_002)
kind: postmortem
fixture_id: slow_query_002
---
Incident on gateway, alert 15 s after the fault began.
Root cause: INSERT statements on the orders table in orders waited on a lock for about 595 ms each; the slow-statement log ('duration: ... statement: ...') rose sharply.
Symptoms: gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
