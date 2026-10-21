title: Connection refused by a dependency
kind: runbook
---
Symptom: callers log ConnectError / Errno 111 for one dependency, often in bursts, with no matching server spans.
The dependency's listener is not accepting connections: a crash-looping worker, a full accept backlog, or a port change. Check the dependency's restarts and readiness, and whether every caller sees the refusals at the same moments.
