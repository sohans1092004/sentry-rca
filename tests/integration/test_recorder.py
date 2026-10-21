import json
import uuid
from datetime import UTC, datetime, timedelta

import pyarrow.parquet as pq
import pytest

from common import deploys, synthetic
from common.config import DEMO_TENANT_ID
from processors.convert import LOG_COLUMNS, METRIC_COLUMNS, SPAN_COLUMNS, convert_logs, convert_metrics, convert_traces
from recorder.dataset import DatasetMismatch, export, read_ch
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
    deploys.record(ch, {"id": str(uuid.uuid4()), "tenant_id": DEMO_TENANT_ID, "service": "orders",
                        "version": "orders-v1.2.0", "started_at": now - timedelta(seconds=30),
                        "finished_at": now - timedelta(seconds=10)})  # fmt: skip


def _record(ch, pg, out, now):
    start, end = now - timedelta(minutes=5), now + timedelta(minutes=5)
    tables = {t: read_ch(ch, t, DEMO_TENANT_ID, start, end) for t in ("metrics", "logs", "spans")}
    tables["deploys"] = deploys.recent(ch, DEMO_TENANT_ID, start, end)
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


def test_fault_start_is_refused_while_an_incident_lies_in_the_alert_baseline(pg):
    """A29: an incident resolved 10 minutes ago lies inside the 31-minute alert baseline, so this is not
    a clean fault start; once it lies before the baseline, it is."""
    from recorder.record import alert_baseline, incident_in_baseline

    now = datetime.now(UTC)
    assert alert_baseline(pg) == timedelta(seconds=60 + 1800)
    assert incident_in_baseline(pg, now) is None
    pg.execute(
        "INSERT INTO incidents (id, tenant_id, fingerprint, service, status, first_anomaly_at, last_seen) "
        "VALUES (%s, %s, 'gateway|slo|x', 'gateway', 'resolved', %s, %s)",
        (str(uuid.uuid4()), DEMO_TENANT_ID, now - timedelta(minutes=20), now - timedelta(minutes=13)),
    )
    reason = incident_in_baseline(pg, now)
    assert reason is not None and "in the alert baseline" in reason, "a fault would start with a dirty baseline"
    assert incident_in_baseline(pg, now + timedelta(minutes=30)) is None  # resolved 40 min before then
    pg.execute(
        "INSERT INTO incidents (id, tenant_id, fingerprint, service, status, first_anomaly_at, last_seen) "
        "VALUES (%s, %s, 'gateway|slo|y', 'gateway', 'open', %s, %s)",
        (str(uuid.uuid4()), DEMO_TENANT_ID, now, now),
    )
    assert incident_in_baseline(pg, now + timedelta(minutes=30)) == "1 incidents open"
