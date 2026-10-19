# ADR-006: A causal-ranking heuristic, not formal causal inference, and its blind spot

**Status:** Draft (written in Phase 1 for the `noisy_neighbor` fixtures; the heuristic itself is
built in Phase 2, and its measured accuracy goes here then).

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

## Consequences

- Request-connected chains (deploy → slow query → pool exhaustion → retry storm → CPU) are the
  heuristic's strength; shared-host contention is its known limit, measured rather than hidden.
- Closing the gap would take host-level topology (which containers share a node or core) as a
  second source of edges, so a host neighbour enters the scope. Out of scope for this project; it is
  the first thing a production version would add.
- TODO (Phase 2): baseline accuracy on the request-connected fixtures vs the `noisy_neighbor`
  fixtures, and how often each ranker blames a victim.
