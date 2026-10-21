title: Worker or thread pool starvation
kind: runbook
---
Symptom: latency climbs and requests queue while CPU stays low.
Blocking calls hold every worker of an async server or thread pool. Find the blocking call in the slow spans and move it off the request path or into a bounded executor.
