title: CPU saturation and noisy neighbours
kind: runbook
---
Symptom: services slow down together with no error and no dependency explaining it.
Check CPU throttling and host-level usage: another workload on the same host or core can starve services without any trace connecting them. Telemetry from the services themselves will not name the neighbour; host metrics will.
