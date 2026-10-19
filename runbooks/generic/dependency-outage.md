title: Third-party dependency outage
kind: runbook
---
Symptom: calls to an external provider time out or fail; 'provider charge failed' warnings; retries.
Confirm with client spans to the provider (peer.service) and their error status. Check the provider's status page. Mitigate with circuit breaking and shorter timeouts; retries without backoff make it worse.
