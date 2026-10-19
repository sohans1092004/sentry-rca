"""Load a fixture dataset into an isolated ClickHouse database (Phase 2's eval harness uses this).

python -m recorder.load data/fixtures/<id>/v1 <database>
"""

import sys
from pathlib import Path

from clickhouse_connect.driver.client import Client

from common import db
from common.migrate import migrate_clickhouse
from recorder.dataset import TABLES, read_parquet, verify_hashes


def load(dataset: Path, ch: Client, database: str) -> None:
    """Create `database` from scratch, insert every table, then prove it matches the manifest."""
    ch.command(f"DROP DATABASE IF EXISTS `{database}`")
    migrate_clickhouse(ch, database)
    for name in TABLES:
        rows = read_parquet(dataset / f"{name}.parquet")
        if rows:
            cols = TABLES[name]["schema"].names
            ch.insert(name, [[r[c] for c in cols] for r in rows], column_names=cols, database=database)
    verify_hashes(dataset, ch, database)


if __name__ == "__main__":
    load(Path(sys.argv[1]), db.clickhouse("default"), sys.argv[2])
    print("loaded and verified", sys.argv[1], "->", sys.argv[2])
