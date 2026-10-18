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
BATCH = 100  # events per OTLP request
DOCKER = "docker"


def sender(rate_per_proc: float, until: float, idx: int, sent: "mp.Value") -> None:  # type: ignore[type-arg]
    builders = [("/v1/metrics", lambda: synthetic.metrics(f"loadgen-{idx}", BATCH - 6)),  # +6 histogram rows
                ("/v1/logs", lambda: synthetic.logs(f"loadgen-{idx}", BATCH)),
                ("/v1/traces", lambda: synthetic.traces(f"loadgen-{idx}", BATCH))]  # fmt: skip
    headers = {"Content-Type": "application/x-protobuf", "x-sentry-service": f"loadgen-{idx}"}
    interval, n = BATCH / rate_per_proc, 0
    next_t = time.monotonic()
    with httpx.Client(base_url=COLLECTOR, timeout=10) as http:
        while time.monotonic() < until:
            path, build = builders[n % 3]
            try:
                if http.post(path, content=build().SerializeToString(), headers=headers).status_code < 300:
                    with sent.get_lock():
                        sent.value += BATCH
            except httpx.HTTPError:
                pass
            n += 1
            next_t += interval
            time.sleep(max(0.0, next_t - time.monotonic()))


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
    ap.add_argument("--max", type=int, default=40000)
    ap.add_argument("--procs", type=int, default=8)
    args = ap.parse_args()
    rates = [r for r in (1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 12500, 15000, 20000, 25000, 30000, 40000)
             if args.start <= r <= args.max]  # fmt: skip
    started = datetime.now(UTC)
    steps, growing = [], 0
    for rate in rates:
        sent = mp.Value("q", 0)
        until = time.monotonic() + args.step_s
        procs = [mp.Process(target=sender, args=(rate / args.procs, until, i, sent)) for i in range(args.procs)]
        t0 = time.monotonic()
        for p in procs:
            p.start()
        time.sleep(args.step_s / 2)
        mid = lag()
        for p in procs:
            p.join()
        end = lag()
        step = {"target_eps": rate, "sent_eps": round(sent.value / (time.monotonic() - t0)), "lag_mid": mid,
                "lag_end": end, "docker_stats": docker_stats()}  # fmt: skip
        prev = sum(steps[-1]["lag_end"].values()) if steps else 0
        unbounded = sum(end.values()) > max(sum(mid.values()), prev) and sum(end.values()) > rate  # > 1 s behind
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
    out = ROOT / "runs" / f"ceiling-{started:%Y%m%dT%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str))
    print("drained after", drained_at, "s; written", out)


if __name__ == "__main__":
    main()
