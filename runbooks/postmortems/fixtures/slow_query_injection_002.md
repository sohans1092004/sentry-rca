title: Postmortem: slow query incident (slow_query_injection_002)
kind: postmortem
fixture_id: slow_query_injection_002
---
Incident on gateway, alert 15 s after the fault began.
Root cause: UPDATE statements on the holds table in inventory waited on a lock for about 344 ms each; the slow-statement log ('duration: ... statement: ...') rose sharply.
Symptoms: payments, orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
