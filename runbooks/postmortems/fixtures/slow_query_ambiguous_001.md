title: Postmortem: slow query incident (slow_query_ambiguous_001)
kind: postmortem
fixture_id: slow_query_ambiguous_001
---
Incident on gateway, alert 17 s after the fault began.
Root cause: INSERT statements on the orders table in orders waited on a lock for about 299 ms each; the slow-statement log ('duration: ... statement: ...') rose sharply; at the same time, the deploy of inventory-v1.29.0 to inventory shipped a regression that added about 370 ms to every request. A deploy to payments shortly before was unrelated.
Symptoms: gateway, payments slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
