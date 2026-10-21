title: Postmortem: bad deploy incident (bad_deploy_ambiguous_001)
kind: postmortem
fixture_id: bad_deploy_ambiguous_001
---
Incident on gateway, alert 16 s after the fault began.
Root cause: the external payment provider timed out for most charges from payments; retries ('provider charge failed ... retrying: timed out') multiplied the slow calls; at the same time, the deploy of inventory-v1.28.0 to inventory shipped a regression that added about 668 ms to every request.
Symptoms: gateway, orders, payments slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
