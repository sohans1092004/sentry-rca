title: High request latency at the edge
kind: runbook
---
Symptom: p95 latency at the gateway rises above its baseline.
First look at traces of slow requests: find the child span that holds most of the parent's time; that service is where to dig. Compare its latency, error rate, CPU and memory against the last hour. Check for a deploy shortly before the rise. Latency that rises in every service at once, with no dominant child span, points at shared infrastructure or load, not one service.
