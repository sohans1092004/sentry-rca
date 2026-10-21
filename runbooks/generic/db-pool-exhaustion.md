title: Database connection pool exhaustion
kind: runbook
---
Symptom: 'QueuePool limit of size ... connection timed out' errors, requests waiting for a connection, db.pool.wait rising.
Causes: a pool configured too small, connections held by slow queries, or leaked connections. Check pool size against concurrency, the slowest statements holding connections, and whether callers retry and multiply the load. Callers that retry on timeouts turn a pool problem into a retry storm upstream.
