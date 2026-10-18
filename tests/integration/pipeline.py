"""Helpers to run a real processor loop against test containers."""

import threading
import time
import uuid

from confluent_kafka import Consumer, Producer, TopicPartition

from processors import runner


def produce(bootstrap, topic, payloads, key=b"svc"):
    p = Producer({"bootstrap.servers": bootstrap})
    for v in payloads:
        p.produce(topic, key=key, value=v)
    assert p.flush(30) == 0


def caught_up(bootstrap, group, topic):
    """True when the group's committed offsets reach the end of every partition."""
    c = Consumer({"bootstrap.servers": bootstrap, "group.id": group})
    try:
        parts = c.list_topics(topic, timeout=10).topics[topic].partitions
        tps = [TopicPartition(topic, p) for p in parts]
        committed = {tp.partition: tp.offset for tp in c.committed(tps, timeout=10)}
        return all(max(committed[tp.partition], 0) >= c.get_watermark_offsets(tp, timeout=10)[1] for tp in tps)
    finally:
        c.close()


def drain(bootstrap, signal, topic, dlq, ch, until=None, timeout=60, group=None):
    """Run the processor until until() is true (default: the group has committed everything)."""
    group = group or f"g-{uuid.uuid4().hex[:8]}"
    until = until or (lambda: caught_up(bootstrap, group, topic))
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([topic])
    producer = Producer({"bootstrap.servers": bootstrap, "acks": "all"})
    stop = threading.Event()
    errors = []

    def target():
        try:
            runner.run(signal, consumer, producer, ch, dlq_topic=dlq, stop=stop.is_set, batch_wait_s=0.3)
        except BaseException as e:  # surfaced to the test below
            errors.append(e)

    t = threading.Thread(target=target, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not until() and t.is_alive():
        time.sleep(0.3)
    stop.set()
    t.join(15)
    consumer.close()
    if errors:
        raise errors[0]
    return group


def read_all(bootstrap, topic, expect, timeout=30):
    c = Consumer(
        {"bootstrap.servers": bootstrap, "group.id": f"r-{uuid.uuid4().hex[:8]}", "auto.offset.reset": "earliest"}
    )
    c.subscribe([topic])
    out = []
    deadline = time.monotonic() + timeout
    while len(out) < expect and time.monotonic() < deadline:
        m = c.poll(0.5)
        if m is not None and m.error() is None:
            out.append(m)
    c.close()
    return out
