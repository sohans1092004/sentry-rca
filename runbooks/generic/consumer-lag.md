title: Kafka consumer lag
kind: runbook
---
Symptom: consumer group lag grows.
Compare consume rate with produce rate per partition; a slow processing step or a hot partition caps throughput. Scale consumers up to the partition count; beyond that, add partitions.
