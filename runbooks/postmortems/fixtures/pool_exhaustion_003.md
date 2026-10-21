title: Postmortem: pool exhaustion incident (pool_exhaustion_003)
kind: postmortem
fixture_id: pool_exhaustion_003
---
Incident on gateway, alert 22 s after the fault began.
Root cause: a code path in inventory leaked database connections; the pool of 10 filled, acquires timed out ('QueuePool limit of size 10 ... connection timed out') and payments retried hold confirmations, multiplying the load. A deploy to payments shortly before was unrelated.
Symptoms: payments, orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
