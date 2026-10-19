title: Retry storms
kind: runbook
---
Symptom: call volume to a dependency multiplies while it is failing; caller CPU rises.
Retries without backoff and jitter amplify a partial failure into overload. Identify the retrying caller from attempt counters and client spans; cap retries, add exponential backoff and a retry budget.
