title: Postmortem: slow query incident (slow_query_001)
kind: postmortem
fixture_id: slow_query_001
---
Incident on gateway, alert 17 s after the fault began.
Root cause: UPDATE statements on the stock table in inventory waited on a lock for about 546 ms each; the slow-statement log ('duration: ... statement: ...') rose sharply. A deploy to payments shortly before was unrelated.
Symptoms: payments, orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
