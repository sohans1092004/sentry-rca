title: Load balancer sending traffic to bad instances
kind: runbook
---
Symptom: a fraction of requests fail on one route while others succeed.
An instance that fails health checks still receives traffic, or a stale target remains registered. Compare failures per instance and the target group's health.
