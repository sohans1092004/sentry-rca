title: Container killed for memory (OOM)
kind: runbook
---
Symptom: a service restarts with exit code 137, its memory near the limit just before.
Find what grew (caches, buffers, request bodies), cap it, or raise the limit; an unbounded in-process cache is a common cause.
