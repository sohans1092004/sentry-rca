title: Postmortem: cache stampede after a TTL change
kind: postmortem
---
A config change aligned all product cache TTLs to the hour. At each hour boundary the catalogue database received the full read load at once; p95 latency at the edge tripled for two minutes, three times. Root cause: aligned expiry. Fix: jittered TTLs and request coalescing.
