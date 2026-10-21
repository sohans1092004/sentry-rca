title: Postmortem: bad deploy incident (bad_deploy_002)
kind: postmortem
fixture_id: bad_deploy_002
---
Incident on gateway, alert 18 s after the fault began.
Root cause: the deploy of orders-v1.88.0 to orders shipped a regression: about 32% of requests failed with unhandled exceptions ('Exception in ASGI application: KeyError'). A deploy to inventory shortly before was unrelated.
Symptoms: gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
