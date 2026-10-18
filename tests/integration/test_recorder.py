import json
import uuid
from datetime import UTC, datetime, timedelta

import pyarrow.parquet as pq
import pytest

from common import synthetic
from common.config import DEMO_TENANT_ID
from processors.convert import LOG_COLUMNS, METRIC_COLUMNS, SPAN_COLUMNS, convert_logs, convert_metrics, convert_traces
from recorder.dataset import DatasetMismatch, export, read_ch, read_deploys
from recorder.load import load
from tests.integration.conftest import ch_client


def _seed(ch, pg, now):
    ts = int(now.timestamp() * 1e9)
    for convert, build, table, cols in (
        (convert_metrics, synthetic.metrics, "metrics", METRIC_COLUMNS),
        (convert_logs, synthetic.logs, "logs", LOG_COLUMNS),
        (convert_traces, synthetic.traces, "spans", SPAN_COLUMNS),
    ):
        for i, svc in enumerate(("gateway", "orders", "inventory")):
            ch.insert(table, convert(build(svc, 50, ts_ns=ts + i * 10**9).SerializeToString()).rows, column_names=cols)
    pg.execute(
        "INSERT INTO deploys VALUES (%s, %s, 'orders', 'orders-v1.2.0', %s, %s)",
        (str(uuid.uuid4()), DEMO_TENANT_ID, now - timedelta(seconds=30), now - timedelta(seconds=10)),
    )


def _record(ch, pg, out, now):
    start, end = now - timedelta(minutes=5), now + timedelta(minutes=5)
    tables = {t: read_ch(ch, t, DEMO_TENANT_ID, start, end) for t in ("metrics", "logs", "spans")}
    tables["deploys"] = read_deploys(pg, DEMO_TENANT_ID, start, end)
    return export(out, tables)


def test_fixture_round_trip_identical_counts_and_hashes(ch_db, ch_container, pg, tmp_path):
    ch, _ = ch_db
    now = datetime.now(UTC).replace(microsecond=0)
    _seed(ch, pg, now)
    manifest = _record(ch, pg, tmp_path, now)
    assert {t: m["rows"] for t, m in manifest["tables"].items()} == {
        "metrics": 3 * 56,
        "logs": 150,
        "spans": 150,
        "deploys": 1,
    }

    target = f"fx_{uuid.uuid4().hex[:8]}"
    load(tmp_path, ch_client(ch_container), target)  # raises unless counts and hashes match
    again = _record(ch_client(ch_container, target), pg, tmp_path / "again", now)
    assert again["tables"] == manifest["tables"]


def test_loader_rejects_tampered_dataset(ch_db, ch_container, pg, tmp_path):
    ch, _ = ch_db
    now = datetime.now(UTC).replace(microsecond=0)
    _seed(ch, pg, now)
    _record(ch, pg, tmp_path, now)
    t = pq.read_table(tmp_path / "logs.parquet").to_pylist()
    t[0]["body"] = "tampered"
    from recorder.dataset import write_parquet

    for r in t:
        r["attrs"] = dict(r["attrs"])
    write_parquet(tmp_path / "logs.parquet", "logs", t)
    with pytest.raises(DatasetMismatch, match="logs"):
        load(tmp_path, ch_client(ch_container), f"fx_{uuid.uuid4().hex[:8]}")
    assert json.loads((tmp_path / "manifest.json").read_text())["tables"]["logs"]["rows"] == 150
