title: Postgres lock contention
kind: runbook
---
Symptom: statements waiting, lock timeouts.
Inspect pg_locks and pg_stat_activity for the blocking transaction; long transactions and hot rows are the usual cause.
