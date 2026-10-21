from dataclasses import asdict

import pytest

from injector.scenarios import DEMO, SCENARIOS, TEST_ONLY, plan
from recorder.record import DEV, TEST


@pytest.mark.parametrize("scenario", SCENARIOS + TEST_ONLY)
def test_plan_is_reproducible_from_seed(scenario):
    assert asdict(plan(scenario, 7)) == asdict(plan(scenario, 7))
    assert any(asdict(plan(scenario, 7)) != asdict(plan(scenario, s)) for s in range(8, 20))


def test_labels_follow_spec_and_amendments():
    p = plan("pool_exhaustion", 1)
    assert p.root_cause == {"service": "inventory", "cause_kind": "pool_exhaustion"}
    assert p.symptom_services == ["payments", "orders", "gateway"] and p.expected_outcome == "ROOT_CAUSE_IDENTIFIED"
    assert plan("no_fault", 1).root_cause is None and plan("no_fault", 1).expected_outcome == "INSUFFICIENT_EVIDENCE"
    nn = plan("noisy_neighbor", 1)
    assert nn.root_cause["service"] == "batchjob" and nn.expected_outcome == "INSUFFICIENT_EVIDENCE"  # A3
    bd = plan("bad_deploy", 1)
    assert bd.deploy["service"] == bd.root_cause["service"] == bd.steps[0].service
    assert bd.steps[0].at_s == bd.deploy["rollout_s"]  # the buggy path switches on when the deploy finishes


@pytest.mark.parametrize("seed", range(10))
def test_ambiguous_uses_two_services_and_injection_plants_elsewhere(seed):
    a = plan("slow_query", seed, "ambiguous")
    [alt] = a.acceptable_alternatives
    assert alt["service"] != a.root_cause["service"] and a.expected_outcome == "CONFLICTING_EVIDENCE"
    assert len({s.service for s in a.steps}) >= 2
    i = plan("dependency_outage", seed, "injection")
    planted = [s for s in i.steps if s.kind == "plant"]
    assert i.planted_injection and planted[0].service != i.root_cause["service"]


@pytest.mark.parametrize("entry", DEV + TEST, ids=lambda e: e[0])
def test_campaign_plans_and_confounders(entry):
    """Every campaign entry plans; confounders sit on in-scope demo services that are not causes,
    a harmless deploy 2-10 min before the fault, and sampling only when confounded (A22)."""
    fid, scenario, seed, variant, partner, confounded = entry
    p = plan(scenario, seed, variant, partner, confounded)
    conf = [s for s in p.steps if s.role == "confounder"]
    assert bool(conf) == confounded == (p.sampling is not None)
    causes = {c["service"] for c in [p.root_cause or {}, *p.acceptable_alternatives] if c}
    for s in conf:
        assert s.service in DEMO and s.service not in causes and s.at_s < 0, (fid, s)
    if confounded:
        assert p.confounder_deploy["service"] not in causes and -600 <= p.confounder_deploy["at_s"] <= -120


def test_splits_are_disjoint_and_test_holds_the_new_kinds():
    dev, test = {e[0] for e in DEV}, {e[0] for e in TEST}
    assert not dev & test and len(test) >= 15
    assert all(e[1] not in TEST_ONLY and e[4] not in TEST_ONLY for e in DEV)
    assert set(TEST_ONLY) <= {e[1] for e in TEST} | {e[4] for e in TEST}
    assert sum(1 for e in TEST if e[3] == "ambiguous") >= 3
    for e in DEV, TEST:
        assert 0.4 <= sum(x[5] for x in e) / len(e) <= 0.6
