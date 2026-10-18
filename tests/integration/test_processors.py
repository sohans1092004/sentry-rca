import json
import os
import subprocess
import sys
import time
import uuid

import pytest

from common import synthetic
from tests.integration.conftest import ch_client
from tests.integration.pipeline import drain, produce, read_all

TABLE = {"metrics": "metrics", "logs": "logs", "traces": "spans"}
BUILD = {"metrics": synthetic.metrics, "logs": synthetic.logs, "traces": synthetic.traces}
# rows per payload: metrics(n) -> n gauges + count/sum/mean + 3 buckets
ROWS = {"metrics": lambda n: n + 6, "logs": lambda n: n, "traces": lambda n: n}


def final_count(ch, table):
    return ch.query(f"SELECT count() FROM {table} FINAL").result_rows[0][0]


def raw_count(ch, table):
    return ch.query(f"SELECT count() FROM {table}").result_rows[0][0]


@pytest.mark.parametrize("signal", ["metrics", "logs", "traces"])
def test_same_telemetry_twice_is_one_logical_row(signal, kafka_bootstrap, ch_db, ch_container, topics):
    ch, name = ch_db
    raw, dlq = topics(f"otel.{signal}.raw", f"otel.{signal}.dlq")
    payloads = [BUILD[signal]("orders", 10, ts_ns=time.time_ns() + i * 10**9).SerializeToString() for i in range(5)]
    # At-least-once: the same messages arrive twice, in separate batches (a redelivery after a
    # crash) and within one batch (a producer retry).
    produce(kafka_bootstrap, raw, payloads)
    group = drain(kafka_bootstrap, signal, raw, dlq, ch_client(ch_container, name))
    produce(kafka_bootstrap, raw, payloads + payloads)
    drain(kafka_bootstrap, signal, raw, dlq, ch_client(ch_container, name), group=group)
    assert final_count(ch, TABLE[signal]) == 5 * ROWS[signal](10)


@pytest.mark.parametrize("signal", ["metrics", "logs", "traces"])
def test_malformed_payloads_go_to_dlq_and_processing_continues(signal, kafka_bootstrap, ch_db, ch_container, topics):
    ch, name = ch_db
    raw, dlq = topics(f"otel.{signal}.raw", f"otel.{signal}.dlq")
    build = BUILD[signal]
    good = lambda: build("payments", 3).SerializeToString()  # noqa: E731
    produce(
        kafka_bootstrap,
        raw,
        [
            good(),
            b"\x0a\xff\xff\xff\xff",  # truncated protobuf: field 1 claims a 4 GB length
            build(None, 3).SerializeToString(),  # decodes, but has no service.name
            good(),
        ],
    )
    table = TABLE[signal]
    per = ROWS[signal](3)
    drain(
        kafka_bootstrap,
        signal,
        raw,
        dlq,
        ch_client(ch_container, name),
        until=lambda: final_count(ch, table) >= 2 * per,
        timeout=30,
    )
    dead = read_all(kafka_bootstrap, dlq, expect=2)
    reasons = sorted(json.loads(m.value())["reason"] for m in dead)
    assert len(reasons) == 2
    assert reasons[0].startswith("decode_error")
    assert reasons[1] == "resource has no service.name"
    assert all(json.loads(m.value())["source"]["topic"] == raw for m in dead)
    assert final_count(ch, table) == 2 * per
    assert ch.query(f"SELECT countIf(service = '') FROM {table}").result_rows[0][0] == 0

    # still consuming after the bad payloads
    produce(kafka_bootstrap, raw, [good()])
    drain(
        kafka_bootstrap,
        signal,
        raw,
        dlq,
        ch_client(ch_container, name),
        until=lambda: final_count(ch, table) >= 3 * per,
        timeout=30,
    )
    assert final_count(ch, table) == 3 * per


def test_kill_between_insert_and_commit_loses_nothing(kafka_bootstrap, ch_db, ch_container, topics):
    ch, name = ch_db
    raw, dlq = topics("otel.traces.raw", "otel.traces.dlq")
    produce(kafka_bootstrap, raw, [synthetic.traces("inventory", 10).SerializeToString() for _ in range(20)])
    env = {
        **os.environ,
        "KAFKA_BOOTSTRAP": kafka_bootstrap,
        "CH_HOST": ch_container.get_container_host_ip(),
        "CH_PORT": str(ch_container.get_exposed_port(8123)),
        "CH_DATABASE": name,
        "SOURCE_TOPIC": raw,
        "DLQ_TOPIC": dlq,
        "GROUP_ID": f"g-{uuid.uuid4().hex[:8]}",
    }
    cmd = [sys.executable, "-m", "processors.runner", "traces"]
    crashed = subprocess.run(
        cmd, env={**env, "SENTRY_CRASH_POINT": "between_insert_and_commit"}, timeout=60, capture_output=True
    )
    assert crashed.returncode == 42, crashed.stderr.decode()[-2000:]
    first = final_count(ch, "spans")
    assert first > 0  # the batch reached ClickHouse; its offsets were never committed

    produce(kafka_bootstrap, raw, [synthetic.traces("inventory", 10).SerializeToString() for _ in range(20)])
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and final_count(ch, "spans") < 400:
            time.sleep(0.5)
    finally:
        proc.terminate()
        proc.wait(15)
    assert final_count(ch, "spans") == 400
