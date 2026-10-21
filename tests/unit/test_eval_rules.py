"""Eval rules of Amendments A23, A25 and A27: scoring modes, which postmortems are excluded, the post-hoc
rule for baseline changes once test results exist, and the backend-agreement gate."""

from evals.harness import FixtureResult, RunResult, gate, posthoc_reasons, related_postmortems


def label(fid, scenario, root=None, alts=(), outcome="ROOT_CAUSE_IDENTIFIED"):
    return {"fixture_id": fid, "scenario": scenario, "root_cause": root, "acceptable_alternatives": list(alts),
            "expected_outcome": outcome}  # fmt: skip


def run(rank1, top3=None):
    return RunResult("inv", "ROOT_CAUSE_IDENTIFIED", rank1, top3 or ([rank1] if rank1 else []), 1, 1)


def test_scoring_modes_judge_new_kinds_on_the_service_only():
    root = {"service": "inventory", "cause_kind": "cache_stampede"}
    new = FixtureResult("cache_stampede_t01", label("cache_stampede_t01", "cache_stampede", root))
    wrong_kind = run(("inventory", "slow_query"))
    assert not new.correct(wrong_kind, 1, "exact")
    assert new.correct(wrong_kind, 1, "service") and new.correct(wrong_kind, 1, "judged")
    assert not new.correct(run(("orders", "cache_stampede")), 1, "judged")
    old = FixtureResult("slow_query_001", label("slow_query_001", "slow_query",
                                                {"service": "inventory", "cause_kind": "slow_query"}))  # fmt: skip
    assert not old.correct(run(("inventory", "pool_exhaustion")), 1, "judged")  # a designed-for kind: exact
    assert old.correct(run(("inventory", "pool_exhaustion")), 1, "service")


def test_related_postmortems_cover_the_scenario_and_shared_kinds():
    labels = {
        "pool_exhaustion_001": label("pool_exhaustion_001", "pool_exhaustion",
                                     {"service": "inventory", "cause_kind": "pool_exhaustion"}),
        "pool_exhaustion_002": label("pool_exhaustion_002", "pool_exhaustion",
                                     {"service": "inventory", "cause_kind": "pool_exhaustion"}),
        "slow_query_001": label("slow_query_001", "slow_query", {"service": "inventory", "cause_kind": "slow_query"}),
        "bad_deploy_ambiguous_001": label("bad_deploy_ambiguous_001", "bad_deploy",
                                          {"service": "orders", "cause_kind": "bad_deploy"},
                                          [{"service": "inventory", "cause_kind": "slow_query"}]),
        "no_fault_001": label("no_fault_001", "no_fault", outcome="INSUFFICIENT_EVIDENCE"),
        "no_fault_002": label("no_fault_002", "no_fault", outcome="INSUFFICIENT_EVIDENCE"),
    }  # fmt: skip
    assert related_postmortems(labels["pool_exhaustion_001"], labels) == ("pool_exhaustion_001", "pool_exhaustion_002")
    assert related_postmortems(labels["slow_query_001"], labels) == ("bad_deploy_ambiguous_001", "slow_query_001")
    assert related_postmortems(labels["no_fault_002"], labels) == ("no_fault_001", "no_fault_002")
    unseen = label("slow_query_injection_t01", "slow_query", {"service": "orders", "cause_kind": "slow_query"})
    assert related_postmortems(unseen, labels) == ("bad_deploy_ambiguous_001", "slow_query_001",
                                                   "slow_query_injection_t01")  # fmt: skip


def test_a_baseline_change_after_test_results_needs_a_post_hoc_amendment():
    accepted = {"test_baseline_sha256": "a" * 64}
    assert posthoc_reasons(None, "b" * 64, "") == []  # no test results yet: fixes are free
    assert posthoc_reasons(accepted, "a" * 64, "") == []  # unchanged
    assert posthoc_reasons(accepted, "b" * 64, "| A30 | 2.5 | §12 | fix |")  # changed, not logged
    spec = "| A30 | 2.5 | §12 | Post-hoc baseline change bbbbbbbbbbbb: reason; before/after kept |"
    assert posthoc_reasons(accepted, "b" * 64, spec) == []


def test_gate_blocks_on_any_backend_mismatch():
    ok = {"gold_rejected": 0, "out_of_scope_allowed": 0, "backend_mismatches": 0, "top1": None}
    assert gate(ok, None) == []
    assert gate({**ok, "backend_mismatches": 1}, None) == ["1 tool calls gave different rows on Parquet (must be 0)"]


def test_paired_comparison_counts_fixtures_and_the_sign_test_is_exact():
    from evals.harness import FixtureResult, RunResult, paired, sign_test

    label = {"expected_outcome": "ROOT_CAUSE_IDENTIFIED", "root_cause": {"service": "inv", "cause_kind": "slow_query"},
             "acceptable_alternatives": []}  # fmt: skip

    def fr(fid, hits):
        runs = [RunResult(f"{fid}{i}", "ROOT_CAUSE_IDENTIFIED", ("inv", "slow_query") if i < hits else ("x", "other"),
                          [], 0, 0) for i in range(5)]  # fmt: skip
        return FixtureResult(fid, label, runs)

    agent = [fr("a", 5), fr("b", 3), fr("c", 0)]
    base = [fr("a", 0), fr("b", 3), fr("c", 1)]
    p = paired(agent, base)
    assert p["top1_tally"] == {"win": 1, "tie": 1, "loss": 1}
    assert p["per_fixture"]["a"]["top1"] == {"agent": 5, "baseline": 0, "of": 5, "verdict": "win"}
    assert sign_test(1, 1) == 1.0 and sign_test(0, 0) is None
    assert abs(sign_test(8, 0) - 2 / 256) < 1e-12
