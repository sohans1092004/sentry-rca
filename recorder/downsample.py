"""metrics_1h job (SPEC §4.1, Amendment A10): aggregate closed hours from deduplicated raw metrics.

Each run recomputes the last RECOMPUTE closed hours (late data from a processor backlog lands in an
hour after it closed) plus any older closed hour still in raw retention that was never computed.
"""

from datetime import UTC, datetime, timedelta

from clickhouse_connect.driver.client import Client

RECOMPUTE = 2  # closed hours recomputed every run
RAW_RETENTION = timedelta(days=7)

HOUR_SQL = """
INSERT INTO metrics_1h
SELECT tenant_id, service, metric, cityHash64(mapKeys(labels), mapValues(labels)) AS labels_hash,
       any(labels), toStartOfHour(ts) AS hour,
       avg(value), min(value), max(value), sum(value), count(), now64(3)
FROM (
  SELECT tenant_id, service, metric, labels, ts, value FROM metrics
  WHERE ts >= {h:DateTime64(3)} AND ts < {h:DateTime64(3)} + INTERVAL 1 HOUR
  ORDER BY point_id LIMIT 1 BY point_id  -- one row per stable ID: a redelivered copy counts once
)
GROUP BY tenant_id, service, metric, labels_hash, hour
"""


def _hour(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def downsample(ch: Client, now: datetime) -> list[datetime]:
    current = _hour(now)
    oldest = _hour(now - RAW_RETENTION) + timedelta(hours=1)
    done = {
        h.replace(tzinfo=UTC)
        for (h,) in ch.query(
            "SELECT DISTINCT hour FROM metrics_1h WHERE hour >= {o:DateTime}", parameters={"o": oldest}
        ).result_rows
    }
    have_raw = {
        h.replace(tzinfo=UTC)
        for (h,) in ch.query(
            "SELECT DISTINCT toStartOfHour(ts) FROM metrics WHERE ts >= {o:DateTime64(3)} AND ts < {c:DateTime64(3)}",
            parameters={"o": oldest, "c": current},
        ).result_rows
    }
    recent = {current - timedelta(hours=i) for i in range(1, RECOMPUTE + 1)}
    hours = sorted(h for h in have_raw if h not in done or h in recent)
    for h in hours:
        ch.command(HOUR_SQL, parameters={"h": h})
    return hours
