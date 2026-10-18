"""Alert Engine (SPEC §2.1, §9): evaluate rules over ClickHouse, fingerprint, upsert incidents,
publish incidents.opened. No LLM (ADR-004).

    python -m alerting.engine
"""

import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from clickhouse_connect.driver.client import Client
from confluent_kafka import KafkaException, Producer

from alerting.rules import Window, check, quantile_ms
from common import config, db

EVAL_INTERVAL_S = 5.0
RESOLVE_AFTER = timedelta(minutes=3)


@dataclass
class Rule:
    id: str
    tenant_id: str
    service: str
    metric: str
    condition: dict[str, Any]

    @property
    def fingerprint(self) -> str:  # service + condition + rule id (SPEC §4.2)
        return f"{self.service}|{self.condition['name']}|{self.id}"


def trigger_id(incident_id: str) -> str:
    """Deterministic event id: every (re)publish of one incident's opening carries the same id, so
    the consumer's (incident_id, trigger_id) key makes redelivery harmless (SPEC §6, §15 row 4)."""
    return f"opened:{incident_id}"


def load_rules(conn: psycopg.Connection[tuple[Any, ...]]) -> list[Rule]:
    rows = conn.execute(
        "SELECT id::text, tenant_id::text, service, metric, condition FROM alert_rules WHERE enabled"
    ).fetchall()
    return [Rule(*r) for r in rows]


def read_window(ch: Client, rule: Rule, now: datetime) -> Window:
    c = rule.condition
    window_start = now - timedelta(seconds=c["window_s"])
    params = {"t": rule.tenant_id, "s": rule.service, "start": window_start, "end": now}
    counts = ch.query(
        "SELECT labels['http.response.status_code'], sum(value) FROM metrics FINAL "
        "WHERE tenant_id = {t:String} AND service = {s:String} AND metric = {m:String} "
        "AND ts > {start:DateTime64(3)} AND ts <= {end:DateTime64(3)} GROUP BY 1",
        parameters={**params, "m": rule.metric + ".count"},
    ).result_rows
    bucket_sql = (
        "SELECT {g} toFloat64(labels['le']), sum(value) FROM metrics FINAL "
        "WHERE tenant_id = {{t:String}} AND service = {{s:String}} AND metric = {{m:String}} "
        "AND ts > {{start:DateTime64(3)}} AND ts <= {{end:DateTime64(3)}} GROUP BY ALL"
    )
    bm = rule.metric + ".bucket"
    buckets = ch.query(bucket_sql.format(g=""), parameters={**params, "m": bm}).result_rows
    baseline_s = max((x.get("baseline_s", 0) for x in c["any_of"]), default=0)
    per_minute: dict[datetime, dict[float, float]] = {}
    if baseline_s:
        rows = ch.query(
            bucket_sql.format(g="toStartOfMinute(ts),"),
            parameters={**params, "m": bm, "start": window_start - timedelta(seconds=baseline_s), "end": window_start},
        ).result_rows
        for minute, le, n in rows:
            per_minute.setdefault(minute, {})[le] = n
    q = next((x["quantile"] for x in c["any_of"] if x["kind"] == "latency_zscore"), 0.95)
    baseline = [v for b in per_minute.values() if (v := quantile_ms(b, q)) is not None]
    return Window(
        status_counts={str(code): float(n) for code, n in counts},
        buckets={le: float(n) for le, n in buckets},
        baseline_p95_ms=baseline,
    )


def record_alert(
    conn: psycopg.Connection[tuple[Any, ...]],
    tenant_id: str,
    fingerprint: str,
    service: str,
    first_anomaly_at: datetime,
    now: datetime,
) -> tuple[str, bool]:
    """Open an incident, or count a repeat against the open one. The partial unique index
    incidents_one_open is what makes this a dedup (SPEC §4.2, §15 row 3). Returns (id, opened)."""
    row = conn.execute(
        "INSERT INTO incidents (id, tenant_id, fingerprint, service, status, first_anomaly_at, last_seen) "
        "VALUES (%s, %s, %s, %s, 'open', %s, %s) "
        "ON CONFLICT (tenant_id, fingerprint) WHERE status <> 'resolved' "
        "DO UPDATE SET last_seen = EXCLUDED.last_seen, alert_count = incidents.alert_count + 1 "
        "RETURNING id::text, (xmax = 0)",
        (str(uuid.uuid4()), tenant_id, fingerprint, service, first_anomaly_at, now),
    ).fetchone()
    assert row is not None
    return row[0], bool(row[1])


def resolve_stale(conn: psycopg.Connection[tuple[Any, ...]], now: datetime) -> list[str]:
    rows = conn.execute(
        "UPDATE incidents SET status = 'resolved' WHERE status <> 'resolved' AND last_seen < %s RETURNING id::text",
        (now - RESOLVE_AFTER,),
    ).fetchall()
    return [r[0] for r in rows]


def publish_opened(producer: Producer, topic: str, incident: dict[str, Any]) -> None:
    failed: list[str] = []
    producer.produce(
        topic,
        key=f"{incident['tenant_id']}:{incident['fingerprint']}".encode(),
        value=json.dumps({**incident, "trigger_id": trigger_id(incident["incident_id"])}, default=str).encode(),
        on_delivery=lambda err, _m: failed.append(str(err)) if err else None,
    )
    producer.flush(30)
    if failed:
        raise KafkaException(f"incidents.opened delivery failed: {failed}")


INCIDENT_SQL = (
    "SELECT id::text AS incident_id, tenant_id::text, fingerprint, service, opened_at, first_anomaly_at "
    "FROM incidents WHERE {where}"
)


def _incident(conn: psycopg.Connection[tuple[Any, ...]], where: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    cur = conn.execute(INCIDENT_SQL.format(where=where).encode(), params)
    cols = [d.name for d in cur.description or []]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def republish_open(conn: psycopg.Connection[tuple[Any, ...]], producer: Producer, topic: str) -> int:
    """At-least-once without an outbox: a crash between the incident commit and the publish is
    healed on startup by republishing every non-resolved incident. Redelivery is harmless."""
    incidents = _incident(conn, "status <> 'resolved'", ())
    for inc in incidents:
        publish_opened(producer, topic, inc)
    return len(incidents)


def _log(**fields: Any) -> None:
    print(json.dumps({"ts": datetime.now(UTC).isoformat(), **fields}, default=str), flush=True)


class Engine:
    def __init__(self, conn: psycopg.Connection[tuple[Any, ...]], ch: Client, producer: Producer, topic: str):
        self.conn, self.ch, self.producer, self.topic = conn, ch, producer, topic
        self.streak: dict[str, tuple[int, datetime]] = {}  # rule id -> (consecutive breaches, first breach)

    def tick(self, now: datetime) -> None:
        for rule in load_rules(self.conn):
            breach = check(rule.condition, read_window(self.ch, rule, now))
            if breach is None:
                self.streak.pop(rule.id, None)
                continue
            n, first = self.streak.get(rule.id, (0, now))
            self.streak[rule.id] = (n + 1, first)
            if n + 1 < rule.condition["consecutive"]:
                continue
            incident_id, opened = record_alert(self.conn, rule.tenant_id, rule.fingerprint, rule.service, first, now)
            _log(event="alert", rule=rule.id, fingerprint=rule.fingerprint, incident_id=incident_id, opened=opened,
                 **breach)  # fmt: skip
            if opened:
                [inc] = _incident(self.conn, "id = %s", (incident_id,))
                publish_opened(self.producer, self.topic, inc)
                _log(event="incident_opened", **inc)
        for incident_id in resolve_stale(self.conn, now):
            _log(event="incident_resolved", incident_id=incident_id)

    def run(self) -> None:
        _log(event="startup_republish", count=republish_open(self.conn, self.producer, self.topic))
        while True:
            started = time.monotonic()
            try:
                self.tick(datetime.now(UTC))
            except Exception as e:  # a failed tick (ClickHouse down) is logged and retried next tick
                _log(event="tick_failed", error=str(e)[:300])
            time.sleep(max(0.0, EVAL_INTERVAL_S - (time.monotonic() - started)))


def main() -> None:
    producer = Producer({"bootstrap.servers": config.KAFKA_BOOTSTRAP, "acks": "all", "enable.idempotence": True})
    Engine(db.postgres(), db.clickhouse(), producer, config.INCIDENTS_OPENED_TOPIC).run()


if __name__ == "__main__":
    main()
