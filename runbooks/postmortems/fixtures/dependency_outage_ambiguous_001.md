title: Postmortem: dependency outage incident (dependency_outage_ambiguous_001)
kind: postmortem
fixture_id: dependency_outage_ambiguous_001
---
Incident on gateway, alert 19 s after the fault began.
Root cause: the external payment provider timed out for most charges from payments; retries ('provider charge failed ... retrying: timed out') multiplied the slow calls; at the same time, an unbounded in-process cache in inventory grew without limit; memory rose and every request slowed. A deploy to orders shortly before was unrelated.
Symptoms: gateway, orders slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
