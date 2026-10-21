title: Postmortem: no fault incident (no_fault_002)
kind: postmortem
fixture_id: no_fault_002
---
Incident on gateway, alert 17 s after the fault began.
Root cause: there was no single cause: every service showed small random latency at once (background noise), and no deploy, error or dependency explained it.
Symptoms: gateway, orders, payments, inventory slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
