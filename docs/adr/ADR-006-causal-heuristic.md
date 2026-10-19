# ADR-006: A causal-ranking heuristic, not formal causal inference, and its blind spot

**Status:** Accepted (Phase 2). Measured accuracy: `docs/measurements/phase2.md`.

## Context

Investigations must separate root causes from downstream symptoms (SPEC §1.1 item 5). Formal causal
inference (structural models, interventional data) needs far more data and assumptions than a single
incident window offers. SPEC §7.2 instead combines three signals: temporal precedence of anomaly
onsets, trace structure (a child span's time counts toward its parent's latency) and deploy
proximity.

## Decision

Rank candidate causes with the §7.2 heuristic. Treat trace structure as the strongest evidence,
because it is a recorded request-level dependency, not a correlation.

## The blind spot, by design: causes with no trace path

The heuristic, and every tool call, can only reach services inside the investigation scope: the
incident's service plus its dependency-graph neighbours from `service_edges` (SPEC §5.2). Those
edges come from spans. A cause that no span connects to anything is **outside every scope by
construction**.

The `noisy_neighbor` scenario is built to sit exactly there (Amendment A3):

- `batchjob` shares one CPU core with `payments` and `inventory` (`cpuset`, 8× CPU weight, 6–10
  busy workers) and slows them down;
- it emits only its own container CPU/memory metrics; **it has no trace edges**: it never appears in
  `service_edges`, so no investigation of the gateway incident can query or cite it;
- the honest result is therefore **`INSUFFICIENT_EVIDENCE`**, and that is the fixture's expected
  outcome. The label still names `batchjob` as the root cause, for the record, and its `notes` field
  says why (Amendment A13).

What the fixtures measure: how often a ranker, seeing slow `payments` and `inventory` with no
upstream explanation, wrongly blames a victim instead of reporting insufficient evidence. A ranker
that names `payments` or `inventory` as the root cause of a `noisy_neighbor` fixture is scored
wrong.

## How the baseline implements it (`investigation/baseline.py`)

1. **Onsets** come from `get_incident_timeline` (Amendment A20): per service and signal (latency,
   error rate, CPU, memory, pool wait) on the services' own 5 s metric export ticks, against the first
   10 minutes of the window. Ticks, not 30 s buckets: a bucket stamps an onset up to 30 s before the
   data that shows it, which made a true "deploy finished before the onset" claim false.
2. **Temporal precedence is weak here, and the ranker treats it so.** For request-connected faults,
   every upstream service's latency onset lands within ~0.5 s of the cause's (latency propagates
   instantly; the spread is export-tick jitter). Precedence is only a tie-breaking 0.2 of the score.
3. **Trace structure carries the ranking.** For each slow or failing trace from the first onset, walk
   down from the incident service's root span along the failing child, else the child holding the
   most time, while it holds at least half of the root; the service reached is that trace's dominant
   service. Share of traces dominated = 0.4 of the score.
4. **A cause kind needs its own evidence** (0.3): pool-acquire timeouts, slow-query warnings,
   provider failures, memory growth, or a deploy finishing <= 30 min before the service's onset
   (deploy proximity adds up to 0.1). A service that is only slow is a `downstream_symptom`; with no
   candidate at all, the outcome is `INSUFFICIENT_EVIDENCE`.

Every hypothesis is emitted as typed claims citing the rows used, with thresholds set conservatively
below what the cited rows show, so true claims verify (ADR-007). The output is byte-identical across
runs on the same data (tested on every fixture).

## Gold claims stay inside the scope (Amendment A14)

The `noisy_neighbor` fixtures hold a true fact no investigation can cite: the batch job's CPU rose.
It is kept in `label.json` as `out_of_scope_evidence` with its reason ("no trace edge to the incident
service"), never as a gold claim, and a scope test asserts that citing it is rejected during that
fixture's investigation.

## Consequences

- Request-connected chains (deploy → slow query → pool exhaustion → retry storm → CPU) are the
  heuristic's strength; shared-host contention is its known limit, measured rather than hidden.
- Closing the gap would take host-level topology (which containers share a node or core) as a
  second source of edges, so a host neighbour enters the scope. Out of scope for this project; it is
  the first thing a production version would add.
- Measured (Phase 2 eval, `docs/measurements/phase2.md`): baseline outcome per fixture, including
  whether it blames a victim on the `noisy_neighbor` fixtures. Known miss before the full eval: on
  `slow_query_ambiguous_001` both injected causes are found and verified but scored 0.45 apart, so the
  baseline reports one root cause instead of `CONFLICTING_EVIDENCE`: an error-mode fault barely shows
  in slow traces, so trace dominance favours the slow cause.
