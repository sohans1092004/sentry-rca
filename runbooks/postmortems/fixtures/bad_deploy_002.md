title: Postmortem: bad deploy incident (bad_deploy_002)
kind: postmortem
fixture_id: bad_deploy_002
---
Incident on gateway opened 2026-10-19 01:19:27.077953+00:00 (17 s after the fault began).
Root cause: a deploy of orders (orders-v1.88.0) introduced a regression in its request handler.
Symptoms: gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
