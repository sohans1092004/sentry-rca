title: Postmortem: bad deploy incident (bad_deploy_ambiguous_001)
kind: postmortem
fixture_id: bad_deploy_ambiguous_001
---
Incident on gateway opened 2026-10-19 01:40:07.054956+00:00 (19 s after the fault began).
Root cause: a deploy of inventory () introduced a regression in its request handler.
A second, overlapping cause was also present: payments (dependency_outage).
Symptoms: gateway, orders, payments slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
