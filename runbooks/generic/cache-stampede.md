title: Cache stampede
kind: runbook
---
Symptom: database load spikes when many cache entries expire at once.
Look for aligned TTLs or a cache flush just before the spike. Add jittered expiry and request coalescing.
