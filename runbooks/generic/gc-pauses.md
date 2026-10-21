title: Long garbage-collection pauses
kind: runbook
---
Symptom: periodic latency spikes on one service, heap close to its limit.
Large live heaps make collections long. Reduce allocation, cap caches, or give the heap more headroom.
