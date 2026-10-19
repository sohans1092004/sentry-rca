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
SELECT tenant_id, service, metric, cityHash64(mapKeys(l), mapValues(l)) AS labels_hash,
       any(l), toStartOfHour(t) AS hour,
       avg(v), min(v), max(v), sum(v), count(), now64(3)
FROM (
  SELECT tenant_id, service, metric, any(labels) AS l, any(ts) AS t, any(value) AS v FROM metrics
  WHERE ts >= {h:DateTime64(3)} AND ts < {h:DateTime64(3)} + INTERVAL 1 HOUR
  GROUP BY point_id, tenant_id, service, metric  -- one row per stable ID: a redelivered copy counts once
)
GROUP BY tenant_id, service, metric, labels_hash, hour
-- Deduplicated by GROUP BY, not ORDER BY ... LIMIT 1 BY: an hour of the ingestion-ceiling test holds
-- ~4M rows, and sorting it ran ClickHouse past its 1 GiB limit (code 241); grouping peaks at ~200 MiB
-- and spills to disk past 100 MB.
SETTINGS max_bytes_before_external_group_by = 100000000, max_threads = 2
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
