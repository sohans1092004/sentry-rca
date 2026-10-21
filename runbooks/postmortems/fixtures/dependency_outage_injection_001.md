title: Postmortem: dependency outage incident (dependency_outage_injection_001)
kind: postmortem
fixture_id: dependency_outage_injection_001
---
Incident on gateway, alert 14 s after the fault began.
Root cause: the external payment provider timed out for most charges from payments; retries ('provider charge failed ... retrying: timed out') multiplied the slow calls.
Symptoms: orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
