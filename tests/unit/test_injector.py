from dataclasses import asdict

import pytest

from injector.scenarios import SCENARIOS, plan


@pytest.mark.parametrize("scenario", SCENARIOS)
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
    planted = [s for s in i.steps if s.kind == "plant_logs"]
    assert i.planted_injection and planted[0].service != i.root_cause["service"]
