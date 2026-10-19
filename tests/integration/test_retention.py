from datetime import UTC, datetime, timedelta

from common import synthetic
from processors.convert import LOG_COLUMNS, METRIC_COLUMNS, SPAN_COLUMNS, convert_logs, convert_metrics, convert_traces
from recorder.archive import archive
from recorder.dataset import read_parquet
from recorder.downsample import downsample


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


def _1h(ch, metric):
    return ch.query(
        "SELECT sum(points), round(sum(sum_value), 6), min(min_value), max(max_value) FROM metrics_1h FINAL "
        "WHERE service = 'payments' AND metric = {m:String}",
        parameters={"m": metric},
    ).result_rows[0]


def test_metrics_1h_counts_a_twice_delivered_batch_once(ch_db):
    ch, _ = ch_db
    now = datetime.now(UTC)
    hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    batch = convert_metrics(synthetic.metrics("payments", 20, ts_ns=int(hour.timestamp() * 1e9)).SerializeToString())
    ch.insert("metrics", batch.rows, column_names=METRIC_COLUMNS)
    ch.insert("metrics", batch.rows, column_names=METRIC_COLUMNS)  # redelivered after a crash
    current = convert_metrics(synthetic.metrics("payments", 5).SerializeToString())  # the open hour
    ch.insert("metrics", current.rows, column_names=METRIC_COLUMNS)

    assert hour in downsample(ch, now)
    assert _1h(ch, "synthetic.gauge") == (20, 190.0, 0.0, 19.0)  # 20 points once, not 40
    downsample(ch, now)  # the job re-runs over recent hours: a recompute replaces, never adds
    assert _1h(ch, "synthetic.gauge") == (20, 190.0, 0.0, 19.0)
    open_hour = now.replace(minute=0, second=0, microsecond=0)
    assert ch.query("SELECT count() FROM metrics_1h WHERE hour = {h:DateTime}",
                    parameters={"h": open_hour}).result_rows[0][0] == 0  # fmt: skip
