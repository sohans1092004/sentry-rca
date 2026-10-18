from datetime import UTC, datetime, timedelta

from common import synthetic
from processors.convert import LOG_COLUMNS, METRIC_COLUMNS, SPAN_COLUMNS, convert_logs, convert_metrics, convert_traces
from recorder.archive import archive
from recorder.dataset import read_parquet


def test_archive_day_six_once_and_prune_after_90_days(ch_db, tmp_path):
    ch, _ = ch_db
    today = datetime.now(UTC).date()
    day6 = datetime(today.year, today.month, today.day, 12, tzinfo=UTC) - timedelta(days=6)
    ts = int(day6.timestamp() * 1e9)
    ch.insert("logs", convert_logs(synthetic.logs("orders", 40, ts_ns=ts).SerializeToString()).rows,
              column_names=LOG_COLUMNS)  # fmt: skip
    ch.insert("spans", convert_traces(synthetic.traces("orders", 25, ts_ns=ts).SerializeToString()).rows,
              column_names=SPAN_COLUMNS)  # fmt: skip
    stale = tmp_path / "logs" / f"dt={today - timedelta(days=91)}.parquet"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")

    first = archive(ch, today, tmp_path)
    assert len(first) == 4  # logs + spans, for day-6 and the catch-up day-7
    assert len(read_parquet(tmp_path / "logs" / f"dt={day6.date()}.parquet")) == 40
    assert len(read_parquet(tmp_path / "spans" / f"dt={day6.date()}.parquet")) == 25
    assert archive(ch, today, tmp_path) == []  # idempotent
    assert not stale.exists()


def test_metrics_1h_downsample(ch_db):
    ch, _ = ch_db
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    rows = convert_metrics(synthetic.metrics("payments", 20, ts_ns=int(hour.timestamp() * 1e9)).SerializeToString())
    ch.insert("metrics", rows.rows, column_names=METRIC_COLUMNS)
    [(points, avg, lo, hi)] = ch.query(
        "SELECT sum(points), avgMerge(avg_value), min(min_value), max(max_value) FROM metrics_1h "
        "WHERE service = 'payments' AND metric = 'synthetic.gauge'"
    ).result_rows
    assert (points, avg, lo, hi) == (20, 9.5, 0.0, 19.0)
