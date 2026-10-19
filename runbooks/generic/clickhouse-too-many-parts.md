title: ClickHouse: too many parts
kind: runbook
---
Symptom: inserts rejected with TOO_MANY_PARTS.
Inserts are too small or too frequent; batch them (seconds, thousands of rows) and check merges are keeping up.
