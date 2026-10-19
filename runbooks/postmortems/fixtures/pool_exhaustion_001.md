title: Postmortem: pool exhaustion incident (pool_exhaustion_001)
kind: postmortem
fixture_id: pool_exhaustion_001
---
Incident on gateway opened 2026-10-18 21:25:37.730038+00:00 (13 s after the fault began).
Root cause: inventory's database connection pool was exhausted (pool size 1); requests timed out waiting for a connection and payments retried them, multiplying the load.
Symptoms: payments, orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
