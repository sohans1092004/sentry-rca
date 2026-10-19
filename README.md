# Sentry-RCA

An incident-investigation platform where an AI agent proposes root causes, but every claim it makes
is checked against real telemetry by deterministic code, and its accuracy is measured against a
non-AI baseline. Specification: [`docs/SPEC.md`](docs/SPEC.md) (v3, with an Amendments log).

**Status: Phase 1** (telemetry pipeline, alerting, failure injector, fixture recorder). There is no
AI, no LLM and no investigation code yet; those are Phases 2–3. Measured so far: ingestion ceiling
~100k events/s, alert-to-incident 12–20 s for step faults, 1.8 GB RSS with demo traffic
([`docs/measurements/phase1.md`](docs/measurements/phase1.md)).

## What runs

```
demo services (gateway → orders → inventory / payments → inventory) + demo Postgres
  │ OpenTelemetry (traces, metrics, logs; W3C trace context on every call)
  ▼
OTel Collector 0.155.0 (memory limiter, tenant stamp, batching, bounded queue)
  ▼
Redpanda: otel.{metrics,logs,traces}.raw keyed by service, + one DLQ per signal
  ▼
stream processors (one consumer group per signal; validation, stable IDs, commit after insert)
  ▼
ClickHouse: metrics · logs · spans · service_edges · metrics_1h
  ▼
Alert Engine (edge SLO rule, robust z-score) → incidents (Postgres) → incidents.opened
```

## Run it

Needs Docker and [uv](https://docs.astral.sh/uv/). Everything is local and free.

```sh
docker compose -f deploy/compose.yaml up -d --build   # ~1.7 GB RSS with demo traffic
uv sync
uv run python -m injector plan --scenario pool_exhaustion --seed 1     # what would be injected
uv run python -m injector run  --scenario pool_exhaustion --seed 1     # inject it
uv run python -m recorder.record one pool_exhaustion_001               # inject, wait, export a fixture
uv run python -m recorder.load data/fixtures/pool_exhaustion_001/v1 fx_test   # isolated eval DB
```

Host ports: gateway 18080, orders 18081, payments 18082, inventory 18083, batchjob 18084,
ClickHouse 8123, Postgres 5434, demo Postgres 5433, Redpanda 19092, Collector 4318.

## Tests

```sh
uv run pytest tests/unit          # pure logic
uv run pytest tests/integration   # Testcontainers: ClickHouse, Postgres, Redpanda
uv run python tools/guard_checks.py   # remove each safety guard, watch its test fail, restore it
```

## Docs

- [`docs/walkthrough-phase1.md`](docs/walkthrough-phase1.md): one span from a service to a ClickHouse
  row; one injected failure to an incident and an `incidents.opened` message.
- [`docs/measurements/phase1.md`](docs/measurements/phase1.md): every number with its command.
- [`docs/adr/`](docs/adr/): ADR-001 (one ClickHouse store), ADR-003 (Redpanda), ADR-004 (rule-based alerting).
- `fixtures/<id>/v1/`: label, injection record and manifest of each recorded fixture (Parquet stays
  local in `data/fixtures/`).
