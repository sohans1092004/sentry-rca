title: Blocked event loop
kind: runbook
---
Symptom: an async service's latency rises for every endpoint at once while CPU is busy.
A synchronous, CPU-heavy step (a large scan, serialisation, hashing) on the event loop stalls all concurrent requests. Profile, move the work off the loop.
