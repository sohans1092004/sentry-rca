"""Cold retention (SPEC §4.4, Amendment A5): archive logs and spans to local Parquet before the
7-day TTL can delete them, keep archives 90 days. metrics_1h needs no job (materialised view).

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

from clickhouse_connect.driver.client import Client

from common import config, db
from recorder.dataset import read_ch, write_parquet

ARCHIVE = Path(__file__).resolve().parent.parent / "data" / "archive"
KEEP_DAYS = 90


def archive(ch: Client, today: date, root: Path = ARCHIVE, tenant: str = config.DEMO_TENANT_ID) -> list[str]:
    done = []
    for age, partial in ((6, False), (7, True)):
        day = today - timedelta(days=age)
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        end = start + timedelta(days=1) - timedelta(milliseconds=1)
        for table in ("logs", "spans"):
            out = root / table / f"dt={day.isoformat()}.parquet"
            if out.exists():
                continue  # idempotent: a day is archived once
            rows = read_ch(ch, table, tenant, start, end)
            out.parent.mkdir(parents=True, exist_ok=True)
            write_parquet(out, table, rows)
            meta = {"table": table, "day": day.isoformat(), "rows": len(rows), "archived_at": datetime.now(UTC),
                    "possibly_partial": partial}  # fmt: skip
            out.with_suffix(".json").write_text(json.dumps(meta, default=str))
            done.append(str(out))
    for f in root.glob("*/dt=*.parquet"):
        if date.fromisoformat(f.stem.removeprefix("dt=")) < today - timedelta(days=KEEP_DAYS):
            f.unlink()
            f.with_suffix(".json").unlink(missing_ok=True)
    return done


if __name__ == "__main__":
    while True:
        print(
            json.dumps({"event": "archived", "files": archive(db.clickhouse(), datetime.now(UTC).date())}), flush=True
        )
        if "--loop" not in sys.argv:
            break
        time.sleep(6 * 3600)  # runs several times a day; each day is archived once
