title: Postmortem: memory leak incident (memory_leak_001)
kind: postmortem
fixture_id: memory_leak_001
---
Incident on gateway, alert 164 s after the fault began.
Root cause: an unbounded in-process cache in payments grew without limit; memory rose and every request slowed.
Symptoms: orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
