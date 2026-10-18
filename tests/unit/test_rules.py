import json
import math
from pathlib import Path

import pytest

from alerting.rules import Window, check, quantile_ms, robust_z

SEED = (Path(__file__).parents[2] / "common/migrations/postgres/0002_seed.sql").read_text()
CONDITION = json.loads(SEED[SEED.index("'{") + 1 : SEED.index("}')") + 1])
INF = math.inf


def test_quantile_interpolates_within_bucket():
    # 100 requests: 90 in (0, 0.1], 10 in (0.1, 0.5]
    assert quantile_ms({0.1: 90, 0.5: 10, INF: 0}, 0.5) == pytest.approx(100 * 50 / 90, rel=1e-6)
    assert quantile_ms({0.1: 90, 0.5: 10, INF: 0}, 0.95) == pytest.approx(100 + 400 * 0.5)
    assert quantile_ms({0.1: 0, 1.0: 0, INF: 5}, 0.95) == 1000  # +Inf bucket -> its lower bound
    assert quantile_ms({0.1: 0}, 0.95) is None


def test_robust_z_ignores_outliers_and_floors_sigma():
    z, median = robust_z(100.0, [50.0] * 25 + [900.0] * 5)  # 5 contaminated minutes
    assert median == 50.0 and z == pytest.approx(50 / 2.5)  # sigma floored at 5% of median
    z, _ = robust_z(51.0, [50.0] * 30)
    assert z < 4


def healthy(**kw):
    w = Window(status_counts={"200": 300, "404": 3}, buckets={0.05: 290, 0.1: 13, INF: 0},
               baseline_p95_ms=[48.0, 50.0, 52.0] * 5)  # fmt: skip
    for k, v in kw.items():
        setattr(w, k, v)
    return w


def test_healthy_window_does_not_fire():
    assert check(CONDITION, healthy()) is None


def test_error_rate_fires_above_threshold_with_enough_requests():
    assert check(CONDITION, healthy(status_counts={"200": 90, "500": 10}))["kind"] == "error_rate"
    assert check(CONDITION, healthy(status_counts={"200": 96, "503": 4})) is None  # 4 % < 5 %
    assert check(CONDITION, healthy(status_counts={"200": 5, "500": 5})) is None  # < 20 requests


def test_latency_fires_only_with_baseline_and_all_floors():
    slow = {0.05: 100, 0.5: 200, INF: 0}
    assert check(CONDITION, healthy(buckets=slow))["kind"] == "latency_zscore"
    assert check(CONDITION, healthy(buckets=slow, baseline_p95_ms=[50.0] * 9)) is None  # warming up
    # z is huge on a flat 5 ms baseline, but +8 ms is under the 20 ms absolute floor
    assert check(CONDITION, healthy(buckets={0.005: 50, 0.013: 50, INF: 0}, baseline_p95_ms=[5.0] * 20)) is None
