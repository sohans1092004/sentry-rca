title: Memory leak and GC pressure
kind: runbook
---
Symptom: a service's memory grows steadily without levelling off; latency creeps up as it grows.
Confirm with container memory over the last hours. Leaks often come from unbounded caches or accumulating references. A restart is the immediate mitigation; find the growing structure with a heap profile.
