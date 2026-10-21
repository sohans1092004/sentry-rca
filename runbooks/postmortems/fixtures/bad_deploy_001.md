title: Postmortem: bad deploy incident (bad_deploy_001)
kind: postmortem
fixture_id: bad_deploy_001
---
Incident on gateway, alert 21 s after the fault began.
Root cause: the deploy of payments-v1.78.0 to payments shipped a regression that added about 367 ms to every request. A deploy to orders shortly before was unrelated.
Symptoms: orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
