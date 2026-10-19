import json
import uuid
from datetime import UTC, datetime, timedelta

from confluent_kafka import Producer

from alerting.engine import Engine, publish_opened, record_alert, republish_open, resolve_stale
from common.config import DEMO_TENANT_ID
from processors.convert import METRIC_COLUMNS
from tests.integration.pipeline import read_all

FP = "gateway|slo|00000000-0000-4000-8000-0000000000a1"


def incidents(pg):
    return pg.execute("SELECT id::text, status, alert_count FROM incidents ORDER BY opened_at").fetchall()


def open_incidents(pg):
    return pg.execute("SELECT count(*) FROM incidents WHERE status <> 'resolved'").fetchone()[0]


def test_repeated_alerts_make_exactly_one_open_incident(pg):
    t0 = datetime.now(UTC)
    results = [record_alert(pg, DEMO_TENANT_ID, FP, "gateway", t0, t0 + timedelta(seconds=5 * i)) for i in range(7)]
    assert open_incidents(pg) == 1, f"{open_incidents(pg)} open incidents for one condition"
    assert [opened for _, opened in results] == [True] + [False] * 6
    assert incidents(pg) == [(results[0][0], "open", 7)]  # alert_count = N


def test_alert_after_resolve_opens_a_new_incident(pg):
    t0 = datetime.now(UTC)
    first, _ = record_alert(pg, DEMO_TENANT_ID, FP, "gateway", t0, t0)
    assert resolve_stale(pg, t0 + timedelta(minutes=2)) == []  # still within the resolve window
    assert resolve_stale(pg, t0 + timedelta(minutes=4)) == [first]

    new_id, opened = record_alert(pg, DEMO_TENANT_ID, FP, "gateway", t0, t0 + timedelta(minutes=10))
    # (id, status, alert_count) rows: the resolved incident must be untouched and a new one open
    assert [(status, n) for _, status, n in incidents(pg)] == [("resolved", 1), ("open", 1)]
    assert opened and new_id != first


def test_incidents_opened_redelivery_is_one_event_downstream(pg, kafka_bootstrap, topics):
    [topic] = topics("incidents.opened")
    producer = Producer({"bootstrap.servers": kafka_bootstrap, "acks": "all", "enable.idempotence": True})
    now = datetime.now(UTC)
    incident_id, _ = record_alert(pg, DEMO_TENANT_ID, FP, "gateway", now, now)
    publish_opened(producer, topic, {"incident_id": incident_id, "tenant_id": DEMO_TENANT_ID, "fingerprint": FP})
    assert republish_open(pg, producer, topic) == 1  # the engine restarted: everything open goes out again

    msgs = read_all(kafka_bootstrap, topic, expect=2)
    assert len(msgs) == 2 and msgs[0].key() == msgs[1].key() == f"{DEMO_TENANT_ID}:{FP}".encode()
    # Consumer side, as SPEC §6 specifies for the Phase 2 orchestrator: insert keyed on
    # (incident_id, trigger_id) with ON CONFLICT DO NOTHING.
    pg.execute("CREATE TEMP TABLE triggered (incident_id UUID, trigger_id TEXT, UNIQUE (incident_id, trigger_id))")
    for m in msgs:
        event = json.loads(m.value())
        pg.execute(
            "INSERT INTO triggered VALUES (%s, %s) ON CONFLICT (incident_id, trigger_id) DO NOTHING",
            (event["incident_id"], event["trigger_id"]),
        )
    assert pg.execute("SELECT count(*) FROM triggered").fetchone() == (1,)


def _latency_rows(service, start, minutes, slow_from):
    """Per-5s delta histogram points: 20 requests each, ~45 ms before slow_from and ~600 ms after."""
    rows = []
    ts = start
    while ts < start + timedelta(minutes=minutes):
        slow = ts >= slow_from
        buckets = {"0.05": 0 if slow else 20, "0.75": 20 if slow else 0, "+Inf": 0}
        for le, n in buckets.items():
            labels = {"http.response.status_code": "200", "le": le}
            rows.append([DEMO_TENANT_ID, service, "http.server.request.duration.bucket", labels, ts, float(n),
                         uuid.uuid4()])  # fmt: skip
        rows.append([DEMO_TENANT_ID, service, "http.server.request.duration.count",
                     {"http.response.status_code": "200"}, ts, 20.0, uuid.uuid4()])  # fmt: skip
        ts += timedelta(seconds=5)
    return rows


def test_engine_opens_exactly_one_incident_and_publishes(pg, ch_db, kafka_bootstrap, topics):
    ch, _ = ch_db
    [topic] = topics("incidents.opened")
    now = datetime.now(UTC).replace(microsecond=0)
    onset = now - timedelta(seconds=20)
    ch.insert("metrics", _latency_rows("gateway", now - timedelta(minutes=35), 36, onset), column_names=METRIC_COLUMNS)
    producer = Producer({"bootstrap.servers": kafka_bootstrap, "acks": "all"})
    engine = Engine(pg, ch, producer, topic)

    for i in range(6):  # 30 s of evaluations while the latency stays high
        engine.tick(now + timedelta(seconds=5 * i))
    [(incident_id, status, count)] = incidents(pg)
    assert status == "open" and count == 5  # first breach starts the streak; 2nd opens; 4 repeats
    [msg] = read_all(kafka_bootstrap, topic, expect=1)
    event = json.loads(msg.value())
    assert event["incident_id"] == incident_id and event["trigger_id"] == f"opened:{incident_id}"
    assert event["service"] == "gateway"
    first = pg.execute("SELECT first_anomaly_at FROM incidents").fetchone()[0]
    assert first == now  # the first breaching evaluation, not the second (which opened it)


def test_a_previous_incident_does_not_hide_a_new_fault_in_the_baseline(pg, ch_db, kafka_bootstrap, topics):
    """A29: the previous fixture's fault covers 19 of the 30 baseline minutes, at the same latency as the
    new fault. Counted as normal, it makes the new fault look ordinary (z ~ 0, no alert). Excluded as the
    resolved incident's period, the 11 clean minutes are the baseline and the new fault alerts."""
    ch, _ = ch_db
    [topic] = topics("incidents.opened")
    now = datetime.now(UTC).replace(microsecond=0)
    before = now - timedelta(minutes=31)
    old_fault_end = now - timedelta(minutes=12)
    rows = [r for r in _latency_rows("gateway", before, 32, now - timedelta(seconds=20))
            if not (r[4] < old_fault_end and r[4] >= before)]  # fmt: skip
    rows += _latency_rows("gateway", before, 19, before)  # the old fault: slow from its first point
    ch.insert("metrics", rows, column_names=METRIC_COLUMNS)
    pg.execute(  # the old fault's incident, resolved RESOLVE_AFTER (3 min) after it was last seen
        "INSERT INTO incidents (id, tenant_id, fingerprint, service, status, opened_at, first_anomaly_at, last_seen) "
        "SELECT %s, %s, 'gateway|slo|' || id::text, 'gateway', 'resolved', %s, %s, %s FROM alert_rules",
        (
            str(uuid.uuid4()),
            DEMO_TENANT_ID,
            before + timedelta(seconds=20),
            before,
            old_fault_end - timedelta(minutes=3),
        ),
    )
    engine = Engine(pg, ch, Producer({"bootstrap.servers": kafka_bootstrap, "acks": "all"}), topic)
    for i in range(6):
        engine.tick(now + timedelta(seconds=5 * i))
    assert open_incidents(pg) == 1, "the new fault was hidden by the previous fault in the baseline"
