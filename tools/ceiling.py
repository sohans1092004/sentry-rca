"""Ingestion ceiling (SPEC §17): ramp synthetic OTLP into the Collector from 1,000 events/s until
processor lag grows without bound; record per-step send rate, lag per signal and container CPU.

    uv run python tools/ceiling.py [--start 1000] [--step-s 60] [--max 40000]

Events = metric data points + log records + spans (one third each). Lag = messages the processor
consumer group has not committed, summed over partitions. A step "grows without bound" when lag at
the end of the step is above lag at its midpoint and above the previous step's end.
"""

import argparse
import json
import multiprocessing as mp
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from confluent_kafka import Consumer, TopicPartition

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from common import config, synthetic  # noqa: E402

COLLECTOR = "http://localhost:4318"
BATCH = 100  # events per OTLP request (--batch)
DOCKER = "docker"


def sender(rate_per_proc: float, until: float, idx: int, sent: "mp.Value", batch: int) -> None:  # type: ignore[type-arg]
    builders = [("/v1/metrics", lambda: synthetic.metrics(f"loadgen-{idx}", batch - 6)),  # +6 histogram rows
                ("/v1/logs", lambda: synthetic.logs(f"loadgen-{idx}", batch)),
                ("/v1/traces", lambda: synthetic.traces(f"loadgen-{idx}", batch))]  # fmt: skip
    headers = {"Content-Type": "application/x-protobuf", "x-sentry-service": f"loadgen-{idx}"}
    interval, n = batch / rate_per_proc, 0
    next_t = time.monotonic()
    with httpx.Client(base_url=COLLECTOR, timeout=10) as http:
        while time.monotonic() < until:
            path, build = builders[n % 3]
            try:
                if http.post(path, content=build().SerializeToString(), headers=headers).status_code < 300:
                    with sent.get_lock():
                        sent.value += batch
            except httpx.HTTPError:
                pass
            n += 1
            next_t += interval
            time.sleep(max(0.0, next_t - time.monotonic()))


def direct_sender(rate_per_proc: float, until: float, idx: int, sent: "mp.Value", batch: int) -> None:  # type: ignore[type-arg]
    """--direct: the same OTLP payloads produced straight into Redpanda, bypassing the Collector, so the
    processors and ClickHouse are what saturates."""
    from confluent_kafka import Producer

    builders = [("metrics", lambda: synthetic.metrics(f"loadgen-{idx}", batch - 6)),
                ("logs", lambda: synthetic.logs(f"loadgen-{idx}", batch)),
                ("traces", lambda: synthetic.traces(f"loadgen-{idx}", batch))]  # fmt: skip
    producer = Producer({"bootstrap.servers": config.KAFKA_BOOTSTRAP, "linger.ms": 5, "compression.type": "zstd"})
    interval, n = batch / rate_per_proc, 0
    next_t = time.monotonic()
    while time.monotonic() < until:
        signal, build = builders[n % 3]
        producer.produce(config.raw_topic(signal), key=f"loadgen-{idx}".encode(), value=build().SerializeToString())
        producer.poll(0)
        with sent.get_lock():
            sent.value += batch
        n += 1
        next_t += interval
        time.sleep(max(0.0, next_t - time.monotonic()))
    producer.flush(30)


def refused() -> int:
    """Events the Collector receiver refused so far (memory limiter back-pressure)."""
    text = httpx.get("http://localhost:8888/metrics", timeout=10).text
    return int(sum(float(line.rsplit(" ", 1)[1]) for line in text.splitlines()
                   if line.startswith("otelcol_receiver_refused_")))  # fmt: skip


def lag() -> dict[str, int]:
    out = {}
    for signal in config.SIGNALS:
        topic = config.raw_topic(signal)
        c = Consumer({"bootstrap.servers": config.KAFKA_BOOTSTRAP, "group.id": f"sentry-processor-{signal}"})
        parts = c.list_topics(topic, timeout=10).topics[topic].partitions
        tps = [TopicPartition(topic, p) for p in parts]
        committed = {tp.partition: max(tp.offset, 0) for tp in c.committed(tps, timeout=10)}
        out[signal] = sum(c.get_watermark_offsets(tp, timeout=10)[1] - committed[tp.partition] for tp in tps)
        c.close()
    return out


def docker_stats() -> str:
    return subprocess.run([DOCKER, "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
                          capture_output=True, text=True).stdout  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1000)
    ap.add_argument("--step-s", type=int, default=60)
    ap.add_argument("--max", type=int, default=200000)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--direct", action="store_true", help="produce into Redpanda, bypassing the Collector")
    args = ap.parse_args()
    global BATCH
    BATCH = args.batch
    steps_eps = (
        1000,
        2000,
        3000,
        4000,
        5000,
        6000,
        8000,
        10000,
        12500,
        15000,
        20000,
        25000,
        30000,
        40000,
        50000,
        60000,
        80000,
        100000,
        125000,
        150000,
        200000,
    )
    rates = [r for r in steps_eps if args.start <= r <= args.max]
    started = datetime.now(UTC)
    steps, growing = [], 0
    for rate in rates:
        sent = mp.Value("q", 0)
        until = time.monotonic() + args.step_s
        target = direct_sender if args.direct else sender
        procs = [mp.Process(target=target, args=(rate / args.procs, until, i, sent, BATCH))
                 for i in range(args.procs)]  # fmt: skip
        refused0 = 0 if args.direct else refused()
        t0 = time.monotonic()
        for p in procs:
            p.start()
        time.sleep(args.step_s / 2)
        mid = lag()
        stats = docker_stats()  # while the senders are running, not after
        for p in procs:
            p.join()
        end = lag()
        step = {"target_eps": rate, "sent_eps": round(sent.value / (time.monotonic() - t0)), "lag_mid": mid,
                "lag_end": end, "refused_eps": 0 if args.direct else round((refused() - refused0) / args.step_s),
                "docker_stats": stats}  # fmt: skip
        prev = sum(steps[-1]["lag_end"].values()) if steps else 0
        # lag is in messages; each carries ~BATCH events. "Unbounded": still rising at the end of the step,
        # above the previous step, and more than one second of input behind.
        lag_events = sum(end.values()) * BATCH
        unbounded = sum(end.values()) > max(sum(mid.values()), prev) and lag_events > rate
        step["lag_growing"] = unbounded
        steps.append(step)
        print(json.dumps({k: v for k, v in step.items() if k != "docker_stats"}), flush=True)
        print(step["docker_stats"], flush=True)
        growing = growing + 1 if unbounded else 0
        if growing >= 2:
            break
    drained_at = None
    t_end = time.monotonic()
    while time.monotonic() - t_end < 600:
        if sum(lag().values()) == 0:
            drained_at = round(time.monotonic() - t_end)
            break
        time.sleep(5)
    result = {"started": started, "injection_end": datetime.now(UTC), "steps": steps, "drain_s": drained_at,
              "command": " ".join(sys.argv)}  # fmt: skip
    out = ROOT / "runs" / f"ceiling{'-direct' if args.direct else ''}-{started:%Y%m%dT%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str))
    print("drained after", drained_at, "s; written", out)


if __name__ == "__main__":
    main()
