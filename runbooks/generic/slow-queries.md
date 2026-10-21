title: Slow database queries
kind: runbook
---
Symptom: a database statement's duration rises; slow-statement log lines ('duration: ... statement: ...').
Identify the statement from DB client spans, compare its duration with the baseline, check for missing indexes, lock waits and plan changes after a deploy or a data change. A single slow statement on the request path shows up as latency in every caller above it.
