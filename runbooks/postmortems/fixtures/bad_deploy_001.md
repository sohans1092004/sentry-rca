title: Postmortem: bad deploy incident (bad_deploy_001)
kind: postmortem
fixture_id: bad_deploy_001
---
Incident on gateway opened 2026-10-18 21:47:22.649135+00:00 (19 s after the fault began).
Root cause: a deploy of payments (payments-v1.78.0) introduced a regression in its request handler.
Symptoms: orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
