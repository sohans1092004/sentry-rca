"""Stream processor loop: consume a batch, insert into ClickHouse, route rejects to the DLQ,
and only then commit offsets (at-least-once; stable IDs make the redelivery harmless).

    python -m processors.runner metrics|logs|traces
"""

import base64
import json
import os
import sys
import time
from collections.abc import Callable
from typing import Any

from clickhouse_connect.driver.client import Client
from confluent_kafka import Consumer, KafkaError, KafkaException, Message, Producer
from google.protobuf.message import DecodeError

from common import config, db
from processors.convert import SIGNALS, Converted

INSERT_ATTEMPTS = 5
# A batch is bounded by payload bytes, not message count: one OTLP message can carry thousands of
# records, and a 500-message bound let a backlog build ~250k rows of Python objects and OOM-kill the
# processor in a loop (found by the ingestion-ceiling run, docs/measurements/phase1.md M5).
BATCH_BYTES = 1024 * 1024  # logs are densest: 2 MiB of them reached 175 of 192 MiB RSS while draining
CHUNK_MESSAGES = 10  # the most a batch overshoots BATCH_BYTES by


def _crash_point(name: str) -> None:
    # Test hook: SPEC §15 row 13 / commit-after-insert test kills the process exactly here.
    if os.environ.get("SENTRY_CRASH_POINT") == name:
        os._exit(42)


def _envelope(reason: str, msg: Message, record: dict[str, Any] | None) -> bytes:
    body: dict[str, Any] = {
        "reason": reason,
        "source": {"topic": msg.topic(), "partition": msg.partition(), "offset": msg.offset()},
    }
    if record is None:
        body["payload_b64"] = base64.b64encode(msg.value() or b"").decode()
    else:
        body["record"] = record
    return json.dumps(body).encode()


def _insert(ch: Client, table: str, rows: list[list[Any]], columns: list[str]) -> None:
    for attempt in range(1, INSERT_ATTEMPTS + 1):
        try:
            ch.insert(table, rows, column_names=columns)
            return
        except Exception as e:
            if attempt == INSERT_ATTEMPTS:
                raise
            print(json.dumps({"event": "insert_retry", "table": table, "attempt": attempt, "error": str(e)[:200]}))
            time.sleep(min(2**attempt * 0.2, 5))


def process_batch(
    msgs: list[Message],
    convert: Callable[[bytes], Converted],
) -> tuple[list[list[Any]], list[tuple[Message, bytes]]]:
    rows: list[list[Any]] = []
    dlq: list[tuple[Message, bytes]] = []
    for msg in msgs:
        err = msg.error()
        if err is not None:
            if err.code() == KafkaError._PARTITION_EOF:
                continue
            raise KafkaException(err)
        try:
            converted = convert(msg.value() or b"")
        except DecodeError as e:
            dlq.append((msg, _envelope(f"decode_error: {e}", msg, None)))
            continue
        rows.extend(converted.rows)
        dlq.extend((msg, _envelope(r.reason, msg, r.record)) for r in converted.rejects)
    return rows, dlq


def take_batch(consumer: Consumer, max_bytes: int, wait_s: float) -> list[Message]:
    """Messages until max_bytes of (decompressed) payload is reached or wait_s elapses."""
    msgs: list[Message] = []
    size = 0
    deadline = time.monotonic() + wait_s
    while size < max_bytes:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        got = consumer.consume(num_messages=CHUNK_MESSAGES, timeout=left)
        if not got:
            break
        msgs.extend(got)
        size += sum(len(m.value() or b"") for m in got)
    return msgs


def run(
    signal: str,
    consumer: Consumer,
    producer: Producer,
    ch: Client,
    *,
    dlq_topic: str,
    stop: Callable[[], bool] = lambda: False,
    batch_bytes: int = BATCH_BYTES,
    batch_wait_s: float = 1.0,
) -> None:
    table, columns, convert = SIGNALS[signal]
    failed: list[str] = []

    def on_delivery(err: Any, _msg: Any) -> None:
        if err is not None:
            failed.append(str(err))

    while not stop():
        msgs = take_batch(consumer, batch_bytes, batch_wait_s)
        if not msgs:
            continue
        rows, dlq = process_batch(msgs, convert)
        if rows:
            _insert(ch, table, rows, columns)
        for src, value in dlq:
            producer.produce(dlq_topic, key=src.key(), value=value, on_delivery=on_delivery)
        if dlq:
            producer.flush(30)
            if failed:
                raise KafkaException(f"DLQ delivery failed: {failed[:3]}")
        _crash_point("between_insert_and_commit")
        consumer.commit(asynchronous=False)
        print(
            json.dumps({"event": "batch", "signal": signal, "messages": len(msgs), "rows": len(rows), "dlq": len(dlq)}),
            flush=True,
        )


def make_consumer(signal: str, topic: str, group: str | None = None) -> Consumer:
    c = Consumer(
        {
            "bootstrap.servers": config.KAFKA_BOOTSTRAP,
            "group.id": group or f"sentry-processor-{signal}",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    c.subscribe([topic])
    return c


def make_producer() -> Producer:
    return Producer({"bootstrap.servers": config.KAFKA_BOOTSTRAP, "acks": "all", "enable.idempotence": True})


def main() -> None:
    signal = sys.argv[1]
    run(
        signal,
        make_consumer(signal, os.environ.get("SOURCE_TOPIC", config.raw_topic(signal)), os.environ.get("GROUP_ID")),
        make_producer(),
        db.clickhouse(),
        dlq_topic=os.environ.get("DLQ_TOPIC", config.dlq_topic(signal)),
    )


if __name__ == "__main__":
    main()
