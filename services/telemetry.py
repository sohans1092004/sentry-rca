"""OpenTelemetry setup shared by the demo services: traces, metrics (delta temporality, 5 s export)
and logs over OTLP/HTTP to the Collector, plus container CPU/memory gauges."""

import logging
import os
import time
from collections.abc import Iterable
from pathlib import Path

os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")  # http.server.request.duration, seconds

from opentelemetry import metrics, trace  # noqa: E402
from opentelemetry._logs import set_logger_provider  # noqa: E402
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter  # noqa: E402
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter  # noqa: E402
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # noqa: E402
from opentelemetry.metrics import CallbackOptions, Observation  # noqa: E402
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler  # noqa: E402
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor  # noqa: E402
from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider, ObservableGauge, UpDownCounter  # noqa: E402
from opentelemetry.sdk.metrics.export import AggregationTemporality, PeriodicExportingMetricReader  # noqa: E402
from opentelemetry.sdk.resources import Resource  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: E402

DELTA: dict[type, AggregationTemporality] = {
    Counter: AggregationTemporality.DELTA,
    Histogram: AggregationTemporality.DELTA,
    UpDownCounter: AggregationTemporality.CUMULATIVE,
    ObservableGauge: AggregationTemporality.CUMULATIVE,
}
CGROUP = Path("/sys/fs/cgroup")


def _cgroup_cpu_usec() -> float:
    try:
        for line in (CGROUP / "cpu.stat").read_text().splitlines():
            if line.startswith("usage_usec"):
                return float(line.split()[1])
    except OSError:
        pass
    t = os.times()
    return (t.user + t.system) * 1e6


def _cgroup_memory_bytes() -> float:
    try:
        return float((CGROUP / "memory.current").read_text())
    except OSError:
        return 0.0


class _Cpu:
    """Cores used by the whole container since the previous export (like cAdvisor)."""

    def __init__(self) -> None:
        self.last = (time.monotonic(), _cgroup_cpu_usec())

    def __call__(self, _o: CallbackOptions) -> Iterable[Observation]:
        now, usage = time.monotonic(), _cgroup_cpu_usec()
        (t0, u0), self.last = self.last, (now, usage)
        yield Observation((usage - u0) / 1e6 / max(now - t0, 1e-3))


def setup(service: str) -> None:
    resource = Resource.create({"service.name": service, "service.version": os.environ.get("SERVICE_VERSION", "1.0.0")})

    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(), schedule_delay_millis=1000))
    trace.set_tracer_provider(tp)

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(preferred_temporality=DELTA), export_interval_millis=5000
    )  # fmt: skip
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    meter = metrics.get_meter("sentry.demo")
    meter.create_observable_gauge("container.cpu.utilization", [_Cpu()], unit="1")
    meter.create_observable_gauge(
        "container.memory.usage", [lambda _o: [Observation(_cgroup_memory_bytes())]], unit="By"
    )  # fmt: skip

    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(), schedule_delay_millis=1000))
    set_logger_provider(lp)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger().addHandler(LoggingHandler(logger_provider=lp))
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def instrument(app: object) -> None:
    from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="/_fault,/healthz")  # type: ignore[arg-type]
    HTTPXClientInstrumentor().instrument()
    AsyncPGInstrumentor().instrument()  # type: ignore[no-untyped-call]
