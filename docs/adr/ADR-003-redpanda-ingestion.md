# ADR-003: Redpanda (Kafka API) for ingestion, not Pub/Sub or direct writes

**Status:** Draft (Phase 1). Ceiling numbers are in `docs/measurements/phase1.md`.

## Context

Telemetry spikes exactly when an incident starts (SPEC §15 row 1): errors log more, retries
multiply spans. Losing telemetry then loses the evidence the investigation needs. The same raw
stream also has more than one consumer: the stream processors today; replays into fixture or eval
databases, and any future consumer (e.g. a second store), later.

## Options

1. **Collector writes directly to ClickHouse.** Fewest moving parts. A ClickHouse stall or restart
   back-pressures the Collector, whose in-memory queue is the only buffer; no replay; validation and
   stable IDs would live in Collector config.
2. **Redis Pub/Sub (Concord's choice).** Concord broadcasts board ops through Redis Pub/Sub because
   fan-out must be low-latency, a missed broadcast is healed by the next snapshot sync, and no
   consumer needs the stream later. None of that holds here: a missed telemetry message is never
   re-sent, and fire-and-forget delivery drops data during a consumer restart.
3. **Kafka-compatible log (Redpanda).** Durable, replayable, consumer groups with committed offsets,
   one topic per signal keyed by service.

## Decision

Option 3: Redpanda single-node (`--smp 1 --memory 512M`) with `otel.{metrics,logs,traces}.raw`, one
DLQ per signal and `incidents.opened` (SPEC §6). Record keys are the service name for all three
signals (Collector 0.155.0 `message_key_from_metadata_key` + batch `metadata_keys`; C10).
Processors commit offsets only after the ClickHouse insert and the DLQ produce succeed.

Redpanda over Apache Kafka: one binary, no JVM or ZooKeeper/KRaft tuning, a predictable memory
flag — it matters on a laptop budget. Same client API, so the choice is reversible.

## Consequences

- **At-least-once, made harmless.** A kill between insert and commit redelivers the batch; stable
  IDs collapse the copies. Both properties have tests and remove-the-guard checks
  (`tools/guard_checks.out`: `commit_after_insert`, `stable_ids`).
- **Bad payloads are kept, not dropped.** Undecodable messages and invalid records go to
  `otel.<signal>.dlq` with a reason and source offset; the processor keeps consuming (`validation`
  guard check).
- **A spike becomes lag, not loss.** The ingestion-ceiling test (SPEC §17) measures where lag
  stops being bounded and what saturates first. See `docs/measurements/phase1.md` M3.
- **Redpanda down** (§15 row 17): the Collector's bounded `sending_queue` (2,000 batches) holds
  data and retries; overflow is counted in `otelcol_exporter_enqueue_failed_*`.
  TODO: chaos run with Redpanda stopped and the queue overflowing, Phase 4.
- Cost: one more stateful container (≈ 190 MiB RSS measured) and topic setup (`redpanda-init`).
