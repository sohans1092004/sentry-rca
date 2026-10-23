
## 4. Telemetry, alerting and the fault injector

> **The pipeline is at-least-once with stable row IDs, so redelivery is harmless. The faults are injected through the services' normal code paths, because the first version leaked the answer (postmortem 001).**

### 4.1 Pipeline

- **Commit after insert.** Each processor inserts a batch into ClickHouse and only then commits its Kafka offsets ([[processors/runner.py#consumer.commit(asynchronous=False)]]). A crash in between redelivers the batch. Stable row IDs plus ReplacingMergeTree make the duplicate collapse (Phase 1; `docs/walkthrough-phase1.md`).
- **Batches bounded by bytes.** At first, batches were bounded by message count (500). With 500-event messages that was about 250k rows of Python objects, over the processor's 192 MiB limit. A restarted processor met the same backlog and was killed again. Batches are now bounded at 1 MiB of payload ([[processors/runner.py#def take_batch(]]) (`docs/measurements/phase1.md`, M5, run C).
- **Broker outage.** With Redpanda stopped for 60 s, the Collector queued about 60 s of telemetry (12 % of its bound) and drained it within 15 s. No span gap appeared, and no processor restarted **[laptop]** (M4). A longer outage, which would overflow the queue, was not exercised.

### 4.2 Alerting

- **One rule on the edge** (A1). Every scenario surfaces at `gateway`. Finding the cause is the investigation's job, not the alert's. Per-service rules would have opened 3-4 incidents per multi-hop fault, and the SPEC had no cross-service grouping.
- **Robust statistics.** p95 latency is compared with the median and MAD of 1-minute p95s over the trailing 30 minutes ([[alerting/rules.py#def robust_z(]]). The rule needs z > 4, p95 > 1.5x the baseline median, and p95 − median > 20 ms (A8).
- **Two measurement fixes, not rule changes.**
  - The alert baseline excludes incident periods (A29, postmortem 002).
  - The latency histogram got finer buckets (A30). Healthy p95 sat on the 0.1 s bucket edge, so a handful of slow requests moved the interpolated value past the 1.5x ratio.

### 4.3 Faults and fixtures

- **Scenarios.** Six were available while the baseline and the prompt were built (dev): bad_deploy, slow_query, pool_exhaustion, dependency_outage, memory_leak, noisy_neighbor. Four are test-only, never used to build the baseline or the prompt: config_change, cache_stampede, connection_refused, cpu_throttling ([[scenarios#TEST_ONLY = ]]). There are also no-fault fixtures, ambiguous pairs and injection variants.
- **Realistic signals** (A21). A slow query is a lock wait inside the demo database. Pool exhaustion is a connection leak. A bad deploy raises a real `KeyError` through the shared request logger. Planted injection lines arrive as client input. Healthy traffic emits the same vocabulary at low rates.
- **Confounders** in about half the fixtures (A22): a harmless deploy of an in-scope service 2-10 minutes before the fault, a mild unrelated anomaly, and sampling (70 % of logs, 50 % of traces, whole traces) ([[scenarios#SAMPLING = ]]).
- **noisy_neighbor** is a batch job pinned to the same CPU core as two services, with no trace edges (A3). It is outside every scope by design, so the honest outcome is INSUFFICIENT_EVIDENCE. The label keeps the true but uncitable evidence as `out_of_scope_evidence` (A14).
- **Fixtures are versioned datasets.** All telemetry in the window goes to Parquet, plus a label with the cause, the expected outcome, gold claims, confounders and planted row IDs. They are published as a GitHub Release, sha256-verified on fetch, and loaded into an isolated ClickHouse database per eval. The eval reads it through a read-only user and checks it with a content hash before and after (A16).
- **Gold claims** are generated from each fixture's own data with the same pinned arithmetic as the verifier (A11, `recorder/gold.py`). So a true claim that the verifier rejects is a verifier bug, and the eval counts it (false negatives: 0).
