"""Adversarial suite (SPEC §8.3): every case must be rejected, for the stated reason; every honest
variant must pass."""

import pytest

from common.kinds import CAUSE_KINDS
from investigation.verifier import verify, verify_claim
from tests.unit.verifier_helpers import (
    PRE,
    W,
    call,
    deploy_claim,
    deploy_rows,
    hypothesis,
    log_claim,
    logs,
    metric_claim,
    onset_rows,
    points,
    runbook_claim,
    runbook_rows,
    trace,
    trace_claim,
)  # fmt: skip


def check(claim, calls, ranker="baseline", excluded=None):
    return verify_claim(0, claim, calls, ranker, excluded)


def rejects(claim, calls, reason, **kw):
    r = check(claim, calls, **kw)
    assert not r.passed, "the adversarial claim was accepted"
    assert reason in r.reason, r.reason


# --- honest claims pass ------------------------------------------------------------------------


def test_honest_claims_of_every_type_pass():
    p = points()
    assert check(metric_claim(p, mm=2.0), {1: call(1, "query_metrics", p)}).passed  # 50 -> 150 is +2.0
    lg = logs()
    assert check(log_claim(lg), {1: call(1, "query_logs", lg)}).passed
    assert check(trace_claim(), {1: call(1, "query_traces", trace())}).passed
    calls = {1: call(1, "get_recent_deploys", deploy_rows()), 2: call(2, "get_incident_timeline", onset_rows())}
    assert check(deploy_claim(), calls).passed
    assert check(runbook_claim(), {1: call(1, "search_runbooks", runbook_rows())}).passed


# --- common checks -------------------------------------------------------------------------------


def test_fabricated_tool_call_seq():
    p = points()
    rejects(metric_claim(p, seq=99), {1: call(1, "query_metrics", p)}, "not in this investigation")


def test_citation_from_another_investigation():
    p = points()
    other_investigation = {7: call(7, "query_metrics", p)}  # same rows, but another investigation's call
    this_investigation = {1: call(1, "query_metrics", p)}
    assert check(metric_claim(p, seq=7, mm=1.0), other_investigation).passed
    rejects(metric_claim(p, seq=7, mm=1.0), this_investigation, "not in this investigation")


def test_row_id_not_in_snapshot():
    p = points()
    claim = metric_claim(p)
    claim["cites"][0]["row_ids"].append("fabricated-row")
    rejects(claim, {1: call(1, "query_metrics", p)}, "not in the snapshot")


def test_cites_a_rejected_tool_call():
    p = points()
    rejects(metric_claim(p), {1: call(1, "query_metrics", p, decision="rejected")}, "was rejected")


def test_cites_another_rankers_tool_call():
    p = points()
    rejects(metric_claim(p), {1: call(1, "query_metrics", p, ranker="baseline")}, "of the baseline ranker",
            ranker="agent")  # fmt: skip


def test_cites_a_call_without_snapshot():
    p = points()
    rejects(metric_claim(p), {1: call(1, "query_metrics", p, snapshot=None)}, "has no snapshot")


def test_cites_the_wrong_tool_for_the_claim_type():
    lg = logs()
    rejects(log_claim(lg), {1: call(1, "query_metrics", lg)}, "cannot cite query_metrics")


def test_rows_from_the_wrong_service():
    p = points(service="orders")
    rejects(metric_claim(p, service="inventory"), {1: call(1, "query_metrics", p)}, "from another service")
    lg = logs(service="orders")
    rejects(log_claim(lg, service="inventory"), {1: call(1, "query_logs", lg)}, "from another service")


def test_rows_outside_the_window():
    lg = logs(n=40)  # 10 s apart: the last ones fall after the 5-minute window
    rejects(log_claim(lg, min_count=1), {1: call(1, "query_logs", lg)}, "outside the window")
    p = points()
    p[0]["ts"] = "2026-10-18T09:30:00.000Z"  # 30 min before: before the 15-minute baseline too
    rejects(metric_claim(p), {1: call(1, "query_metrics", p)}, "outside window and baseline")


# --- metric_change thresholds ------------------------------------------------------------------


@pytest.mark.parametrize(("mm", "passes"), [(2.0, True), (2.0 + 1e-9, False), (2.0 - 1e-9, True)])
def test_magnitude_exactly_at_just_over_and_just_under(mm, passes):
    p = points(before=50.0, inside=150.0)  # ratio exactly 2.0
    assert check(metric_claim(p, mm=mm), {1: call(1, "query_metrics", p)}).passed is passes


def test_too_few_points_before_or_inside():
    p = points(n=2)
    rejects(metric_claim(p), {1: call(1, "query_metrics", p)}, "baseline points, need 3")


def test_direction_down_needs_a_fall():
    p = points(before=150.0, inside=50.0)
    assert check(metric_claim(p, mm=0.6, direction="down"), {1: call(1, "query_metrics", p)}).passed
    rejects(metric_claim(p, mm=0.6, direction="up"), {1: call(1, "query_metrics", p)}, "rose by")


def test_epsilon_guards_a_zero_baseline():
    p = points(before=0.0, inside=1.0)
    assert check(metric_claim(p, mm=1e5), {1: call(1, "query_metrics", p)}).passed  # 1 / 1e-6
    rejects(metric_claim(p, mm=1e6 + 1), {1: call(1, "query_metrics", p)}, "rose by")


# --- log_pattern: a rise, not mere presence (A24) ------------------------------------------------


def test_log_pattern_present_but_not_elevated():
    lg = logs(n=4, before=4)  # as many lines just before the window as inside it: ratio 1
    rejects(log_claim(lg), {1: call(1, "query_logs", lg)}, "present but not elevated")


def test_log_pattern_rise_exactly_at_and_just_under_the_ratio():
    lg = logs(n=4, before=2)  # ratio 2.0
    assert check(log_claim(lg, min_ratio=2.0), {1: call(1, "query_logs", lg)}).passed
    lg = logs(n=4, before=3)  # ratio 1.33
    rejects(log_claim(lg, min_ratio=2.0), {1: call(1, "query_logs", lg)}, "present but not elevated")


def test_log_pattern_empty_pre_window_counts_as_one():
    assert check(log_claim(logs(n=2), min_count=2), {1: call(1, "query_logs", logs(n=2))}).passed  # 2 / 1
    rejects(log_claim(logs(n=1), min_count=1), {1: call(1, "query_logs", logs(n=1))}, "present but not elevated")


def test_log_pattern_min_ratio_below_the_floor():
    lg = logs(n=4, before=4)
    rejects(log_claim(lg, min_ratio=1.0), {1: call(1, "query_logs", lg)}, "min_ratio must be a number >= 2.0")
    rejects({**log_claim(lg), "min_ratio": None}, {1: call(1, "query_logs", lg)}, "min_ratio must be")


def test_log_pattern_query_that_skips_the_pre_window():
    """Hiding the earlier lines by querying only the window itself must not prove a rise."""
    lg = logs(n=4, before=4)
    inside = [r for r in lg if r["row_id"].startswith("l")]
    only_window = call(1, "query_logs", inside, executed={"service": "inventory", "start": W[0], "end": W[1]})
    rejects(log_claim(lg), {1: only_window}, "does not cover the window and the equal-length window before it")


def test_log_pattern_truncated_query():
    lg = logs(n=4)
    rejects(log_claim(lg), {1: call(1, "query_logs", lg, truncated=True)}, "was truncated")


def test_log_pattern_query_filtered_to_one_trace():
    lg = logs(n=4)
    ex = {"service": "inventory", "start": PRE, "end": W[1], "trace_id": "t1"}
    rejects(log_claim(lg), {1: call(1, "query_logs", lg, executed=ex)}, "filtered to one trace")


# --- trace_dependency --------------------------------------------------------------------------


def test_child_span_not_under_the_parent():
    spans = trace()
    spans[2]["parent_span_id"] = "elsewhere"
    rejects(trace_claim(), {1: call(1, "query_traces", spans)}, "descends from")


def test_child_share_below_claim():
    rejects(trace_claim(share=0.71), {1: call(1, "query_traces", trace(child_ms=700.0))}, "child share")


def test_trace_with_no_cited_child():
    rejects(trace_claim(cited=("g",)), {1: call(1, "query_traces", trace())}, "no cited gateway and inventory")


# --- deploy_precedes_onset ---------------------------------------------------------------------


def deploy_calls(finished=-5, onset_offset=0, deploy_service="orders", onset_service="orders"):
    return {1: call(1, "get_recent_deploys", deploy_rows(finished, deploy_service)),
            2: call(2, "get_incident_timeline", onset_rows(onset_service, onset_offset))}  # fmt: skip


def test_deploy_after_onset():
    rejects(deploy_claim(), deploy_calls(finished=+2), "not before the onset")


def test_deploy_beyond_max_gap():
    rejects(deploy_claim(), deploy_calls(finished=-31), "over the gap")
    assert check(deploy_claim(), deploy_calls(finished=-30)).passed  # exactly at the gap


def test_deploy_for_another_service():
    rejects(deploy_claim(), deploy_calls(deploy_service="payments"), "is for payments")


def test_onset_not_matching_any_timeline_row():
    rejects(deploy_claim(), deploy_calls(onset_offset=61), "within 1 minute")
    rejects(deploy_claim(), deploy_calls(onset_service="payments"), "within 1 minute")


# --- runbook_match -----------------------------------------------------------------------------


def test_runbook_below_threshold():
    rejects(runbook_claim(similarity=0.7), {1: call(1, "search_runbooks", runbook_rows(0.74))},
            "below runbook_min_similarity")  # fmt: skip
    rejects(runbook_claim(similarity=0.9), {1: call(1, "search_runbooks", runbook_rows(0.85))}, "below the claimed")


def test_excluded_fixture_postmortem():
    rows = runbook_rows(0.9, kind="postmortem", fixture_id="pool_exhaustion_001")
    calls = {1: call(1, "search_runbooks", rows)}
    rejects(runbook_claim(), calls, "own postmortem", excluded="pool_exhaustion_001")
    assert check(runbook_claim(), calls, excluded="pool_exhaustion_002").passed  # another fixture's: allowed


# --- hypothesis rules --------------------------------------------------------------------------


def test_root_cause_supported_only_by_runbook_match():
    calls = {1: call(1, "search_runbooks", runbook_rows())}
    h = verify(hypothesis(runbook_claim()), calls, "baseline")
    assert not h.passed and "beyond a similar past incident" in h.reason
    assert verify(hypothesis(runbook_claim(), role="downstream_symptom"), calls, "baseline").passed


@pytest.mark.parametrize("kind", ["latency", "db_overload", "", None, "Pool_Exhaustion"])
def test_cause_kind_outside_the_closed_list(kind):
    p = points()
    h = {**hypothesis(metric_claim(p, mm=1.0)), "cause_kind": kind}
    r = verify(h, {1: call(1, "query_metrics", p)}, "baseline")
    assert not r.passed and "not in the closed list" in r.reason


def test_every_closed_list_kind_is_accepted():
    p = points()
    for kind in CAUSE_KINDS:
        assert verify({**hypothesis(metric_claim(p, mm=1.0)), "cause_kind": kind}, {1: call(1, "query_metrics", p)},
                      "baseline").passed, kind  # fmt: skip


def test_empty_claim_list():
    h = verify(hypothesis(), {}, "baseline")
    assert not h.passed and "at least one claim" in h.reason


def test_one_failed_claim_rejects_the_hypothesis_and_every_result_is_kept():
    p, lg = points(), logs()
    calls = {1: call(1, "query_metrics", p), 2: call(2, "query_logs", lg)}
    h = verify(hypothesis(metric_claim(p, mm=1.0), log_claim(lg, seq=2, min_count=5)), calls, "baseline")
    assert not h.passed and [c.passed for c in h.claims] == [True, False]
    assert "4 cited rows contain" in h.claims[1].reason


def test_the_verifier_does_not_depend_on_gold():
    """The verifier must be independent of recorder/gold.py, which builds the gold claims it is tested against."""
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).parents[2] / "investigation" / "verifier.py").read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m and m.startswith("recorder") for m in imported), imported
