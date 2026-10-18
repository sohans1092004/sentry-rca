"""Environment-driven settings, shared by every component."""

import os

DEMO_TENANT_ID = "00000000-0000-4000-8000-000000000001"

PG_DSN = os.environ.get("PG_DSN", "postgresql://sentry:sentry@localhost:5432/sentry")
CH_HOST = os.environ.get("CH_HOST", "localhost")
CH_PORT = int(os.environ.get("CH_PORT", "8123"))
CH_USER = os.environ.get("CH_USER", "sentry")
CH_PASSWORD = os.environ.get("CH_PASSWORD", "sentry")
CH_DATABASE = os.environ.get("CH_DATABASE", "sentry")
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:19092")

SIGNALS = ("metrics", "logs", "traces")


def raw_topic(signal: str) -> str:
    return f"otel.{signal}.raw"


def dlq_topic(signal: str) -> str:
    return f"otel.{signal}.dlq"


INCIDENTS_OPENED_TOPIC = "incidents.opened"
