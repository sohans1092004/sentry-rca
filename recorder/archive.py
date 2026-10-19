"""Cold retention (SPEC §4.4, Amendment A5): archive logs and spans to local Parquet before the
7-day TTL can delete them, keep archives 90 days; and compute metrics_1h (recorder/downsample.py).

Day D's rows start expiring at D + 7 days, so the job archives D on day D + 6, when D is complete
and nothing has expired yet. Day D - 7 is caught up too if a run was missed; it may already be
partly expired, and its manifest says so.

    python -m recorder.archive [--loop]
"""

import json
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq
from clickhouse_connect.driver.client import Client

from common import config, db
from recorder.dataset import TABLES, arrow_table, read_ch

ARCHIVE = Path(__file__).resolve().parent.parent / "data" / "archive"
KEEP_DAYS = 90


def _archive_day(ch: Client, table: str, tenant: str, start: datetime, out: Path) -> int:
    """One day, read an hour at a time into one Parquet file. A whole day in one deduplicating query
    (~13M spans at demo traffic) exceeded ClickHouse's memory cap and crash-looped the archiver.
    Written to a temporary name first, so a crash never leaves a partial day that looks complete."""
    tmp = out.with_suffix(".parquet.tmp")
    n = 0
    with pq.ParquetWriter(tmp, TABLES[table]["schema"], compression="zstd") as writer:
        for h in range(24):
            hour = start + timedelta(hours=h)
            rows = read_ch(ch, table, tenant, hour, hour + timedelta(hours=1) - timedelta(milliseconds=1))
            if rows:
                writer.write_table(arrow_table(table, rows))
                n += len(rows)
    tmp.replace(out)
    return n


def archive(ch: Client, today: date, root: Path = ARCHIVE, tenant: str = config.DEMO_TENANT_ID) -> list[str]:
    done = []
    for age, partial in ((6, False), (7, True)):
        day = today - timedelta(days=age)
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        for table in ("logs", "spans"):
            out = root / table / f"dt={day.isoformat()}.parquet"
            if out.exists():
                continue  # idempotent: a day is archived once
            out.parent.mkdir(parents=True, exist_ok=True)
            n = _archive_day(ch, table, tenant, start, out)
            meta = {"table": table, "day": day.isoformat(), "rows": n, "archived_at": datetime.now(UTC),
                    "possibly_partial": partial}  # fmt: skip
            out.with_suffix(".json").write_text(json.dumps(meta, default=str))
            done.append(str(out))
    for f in root.glob("*/dt=*.parquet"):
        if date.fromisoformat(f.stem.removeprefix("dt=")) < today - timedelta(days=KEEP_DAYS):
            f.unlink()
            f.with_suffix(".json").unlink(missing_ok=True)
    return done


if __name__ == "__main__":
    from recorder.downsample import downsample

    while True:
        now = datetime.now(UTC)
        ch = db.clickhouse()
        hours = [h.isoformat() for h in downsample(ch, now)]
        print(json.dumps({"event": "retention", "archived": archive(ch, now.date()), "downsampled": hours}), flush=True)
        if "--loop" not in sys.argv:
            break
        time.sleep(3600)  # hourly: metrics_1h closes every hour; each day is archived once
