title: CPU throttling under a container quota
kind: runbook
---
Symptom: latency rises on one service while its CPU use stays flat at its limit and throttled periods climb.
A CPU quota (cgroup cpu.max) lower than the workload needs makes the scheduler pause the container each period. Compare container.cpu.throttled with latency; raise or remove the quota.
