"""Phase 2 remove-the-guard checks. Each removal must make its test fail by showing the unsafe
behaviour (another tenant's rows, an out-of-scope service's rows, an oversized result, a bad claim
accepted, a duplicate investigation, an audit row changed, a wrong outcome), not merely an error."""

IT, U, F = "tests/integration/", "tests/unit/", "tests/fixtures/"
V = U + "test_verifier.py::"


def _v(prop: str, fragment: str, test: str, nth: int = 0) -> dict:
    return {
        "property": f"Verifier: {prop}",
        "file": "investigation/verifier.py",
        "edits": [("require", fragment, nth)],
        "tests": [V + test],
    }


GUARDS_PHASE2: dict[str, dict] = {
    "tenant_filter": {
        "property": "Tenant forced: a query never returns another tenant's rows",
        "file": "investigation/backend.py",
        "edits": [
            (
                '"WHERE tenant_id = {t:String} AND service IN {s:Array(String)} AND metric IN',
                '"WHERE service IN {s:Array(String)} AND metric IN',
            )
        ],
        "tests": [IT + "test_phase2.py::test_clickhouse_queries_never_return_another_tenants_rows"],
    },
    "service_allowlist": {
        "property": "Service allowlist: a service outside scope is rejected, never queried",
        "file": "investigation/tools.py",
        "edits": [("    outside = [s for s in services if s not in scope.services]", "    outside: list[str] = []")],
        "tests": [U + "test_scope_tools.py::test_service_outside_the_allowlist_is_rejected_with_a_reason"],
    },
    "window_clamp": {
        "property": "Window clamp: a request beyond the scope window runs only within it",
        "file": "investigation/tools.py",
        "edits": [
            ("    if start < scope.start:\n        start = scope.start\n", "    if start < scope.start:\n"),
            ("    if end > scope.end:\n        end = scope.end\n", "    if end > scope.end:\n"),
        ],
        "tests": [U + "test_scope_tools.py::test_window_is_clamped_and_recorded"],
    },
    "row_byte_caps": {
        "property": "Row and byte caps: at most 500 rows and 256 KB per result; limits clamped",
        "file": "investigation/tools.py",
        "edits": [
            ("    return rows[:limit], len(rows) > limit", "    return rows, False"),
            ("    if n > cap:\n        clamps.append(key)\n        return cap\n", ""),
        ],
        "extra": [("investigation/snapshots.py", "    while len(content) > MAX_BYTES:", "    while False:")],
        "tests": [U + "test_scope_tools.py::test_limit_and_rows_and_bytes_are_capped"],
    },
    "snapshot_before_return": {
        "property": "Snapshot before return: a citation resolves after the telemetry is deleted",
        "file": "investigation/tools.py",
        "edits": [
            (
                '            snapshot_id, rows, truncated = snap.id, json.loads(snap.content)["rows"], snap.truncated',
                "            snapshot_id, rows, truncated, snap = None, d.rows, d.truncated, None",
            )
        ],
        "tests": [IT + "test_phase2.py::test_citation_resolves_after_the_telemetry_is_deleted"],
    },
    "verifier_fabricated_seq": _v(
        "a citation of a tool call not in this investigation",
        "not in this investigation",
        "test_fabricated_tool_call_seq",
    ),
    "verifier_same_ranker": _v(
        "a citation of another ranker's tool call (A15)", 'ranker")', "test_cites_another_rankers_tool_call"
    ),
    "verifier_rejected_call": _v(
        "a citation of a rejected tool call", "which was rejected", "test_cites_a_rejected_tool_call"
    ),
    "verifier_has_snapshot": _v(
        "a citation of a call without snapshot", "has no snapshot", "test_cites_a_call_without_snapshot"
    ),
    "verifier_claim_tool": _v(
        "a claim citing the wrong tool (A18)", "claim cannot cite", "test_cites_the_wrong_tool_for_the_claim_type"
    ),
    "verifier_row_in_snapshot": _v(
        "a row_id not in the snapshot", "is not in the snapshot", "test_row_id_not_in_snapshot"
    ),
    "verifier_metric_service": _v(
        "metric rows from another service", "is from another service", "test_rows_from_the_wrong_service", 0
    ),
    "verifier_log_service": _v(
        "log rows from another service", "is from another service", "test_rows_from_the_wrong_service", 1
    ),
    "verifier_metric_window": _v(
        "metric rows outside window + baseline", "outside window and baseline", "test_rows_outside_the_window"
    ),
    "verifier_log_window": _v("log rows outside the window", "is outside the window", "test_rows_outside_the_window"),
    "verifier_magnitude": _v(
        "magnitude just over the data", "claimed at least {mm}", "test_magnitude_exactly_at_just_over_and_just_under"
    ),
    "verifier_min_points": _v(
        "fewer than 3 baseline points", "cited baseline points, need 3", "test_too_few_points_before_or_inside"
    ),
    "verifier_log_count": _v(
        "fewer matching log rows than claimed",
        "cited rows contain",
        "test_one_failed_claim_rejects_the_hypothesis_and_every_result_is_kept",
    ),
    "verifier_trace_descent": _v(
        "a child span not under the parent", "descends from a cited", "test_child_span_not_under_the_parent"
    ),
    "verifier_trace_share": _v("a latency share above the data", "child share", "test_child_share_below_claim"),
    "verifier_deploy_before_onset": _v("a deploy after the onset", "not before the onset", "test_deploy_after_onset"),
    "verifier_deploy_gap": _v("a deploy beyond max_deploy_gap", "over the gap", "test_deploy_beyond_max_gap"),
    "verifier_deploy_service": _v("another service's deploy", "is for {d.get", "test_deploy_for_another_service"),
    "verifier_onset_match": _v(
        "an onset matching no timeline row", 'abs(_ts(r["ts"]) - onset)', "test_onset_not_matching_any_timeline_row"
    ),
    "verifier_runbook_threshold": _v(
        "a runbook below runbook_min_similarity", ">= RUNBOOK_MIN_SIMILARITY", "test_runbook_below_threshold"
    ),
    "verifier_own_postmortem": _v(
        "the evaluated fixture's own postmortem", "own postmortem", "test_excluded_fixture_postmortem"
    ),
    "verifier_runbook_only_root": {
        "property": "Verifier: a root cause supported only by runbook_match",
        "file": "investigation/verifier.py",
        "edits": [('    if hypothesis["causal_role"] == "candidate_root_cause" and all(', "    if False and all(")],
        "tests": [V + "test_root_cause_supported_only_by_runbook_match"],
    },
    "verifier_empty_claims": {
        "property": "Verifier: a hypothesis with no claims",
        "file": "investigation/verifier.py",
        "edits": [("    if not isinstance(claims, list) or not claims:", "    if not isinstance(claims, list):")],
        "tests": [V + "test_empty_claim_list"],
    },
    "contamination_sql": {
        "property": "Contamination rule (§12.2, A25): search_runbooks returns no postmortem of the evaluated "
        "fixture or of one with the same scenario",
        "file": "investigation/runbooks.py",
        "edits": [
            (
                '"AND (fixture_id IS NULL OR NOT fixture_id = ANY(%s)) "',
                '"AND (fixture_id IS NULL OR NOT fixture_id = ANY(%s) OR TRUE) "',
            )
        ],
        "tests": [IT + "test_phase2.py::test_same_scenario_postmortems_are_not_returned_by_search_runbooks"],
    },
    "idempotent_investigation": {
        "property": "Idempotent investigation insert: a redelivered trigger creates no second investigation",
        "file": "investigation/orchestrator.py",
        "edits": [('"ON CONFLICT (incident_id, trigger_id) DO NOTHING RETURNING id::text",', '"RETURNING id::text",')],
        "extra": [
            (
                "common/migrations/postgres/0004_investigation.sql",
                "  completed_at TIMESTAMPTZ,\n  UNIQUE (incident_id, trigger_id)\n",
                "  completed_at TIMESTAMPTZ\n",
            )
        ],
        "tests": [IT + "test_phase2.py::test_redelivered_trigger_creates_no_second_investigation"],
    },
    "append_only_grants": {
        "property": "Append-only audit: the app role cannot UPDATE or DELETE a tool_call row",
        "file": "common/migrations/postgres/0005_app_role.sql",
        "edits": [
            (
                "REVOKE ALL ON tool_calls, evidence_snapshots, hypotheses, claims, claim_citations FROM sentry_app;\n"
                "GRANT SELECT, INSERT ON tool_calls",
                "GRANT ALL ON tool_calls",
            )
        ],
        "tests": [IT + "test_phase2.py::test_app_role_cannot_update_or_delete_audit_rows"],
    },
    "conflict_margin": {
        "property": "Conflict margin (§7.5): two causes within the margin give CONFLICTING_EVIDENCE",
        "file": "investigation/outcome.py",
        "edits": [('        if different and top["score"] - other["score"] <= margin:', "        if False:")],
        "tests": [U + "test_scope_tools.py::test_outcome_rules_and_conflict_margin"],
    },
    # --- Phase 2.5 (A23-A28) ---
    "verifier_log_ratio": {
        "property": "Verifier: a log pattern present but not elevated (A24)",
        "file": "investigation/verifier.py",
        "edits": [("_require(ratio >= mr,", "_require(True or ratio >= mr,")],
        "tests": [V + "test_log_pattern_present_but_not_elevated"],
    },
    "verifier_log_ratio_floor": {
        "property": "Verifier: a log_pattern claiming a ratio under 2 (A24)",
        "file": "investigation/verifier.py",
        "edits": [("_require(isinstance(mr, (int, float))", "_require(True or isinstance(mr, (int, float))")],
        "tests": [V + "test_log_pattern_min_ratio_below_the_floor"],
    },
    "verifier_log_coverage": {
        "property": "Verifier: a log query that skips the window before (A24)",
        "file": "investigation/verifier.py",
        "edits": [('_require("start" in ex and "end" in ex', '_require(True or "start" in ex and "end" in ex')],
        "tests": [V + "test_log_pattern_query_that_skips_the_pre_window"],
    },
    "verifier_log_truncated": _v(
        "counts from a truncated log query", "was truncated", "test_log_pattern_truncated_query"
    ),
    "verifier_cause_kind": {
        "property": "Verifier: a cause kind outside the closed list (A23)",
        "file": "investigation/verifier.py",
        "edits": [('    if hypothesis.get("cause_kind") not in CAUSE_KINDS:', "    if False:")],
        "tests": [V + "test_cause_kind_outside_the_closed_list"],
    },
    "cause_kind_schema": {
        "property": "Schema: hypotheses.cause_kind outside the closed list is refused by Postgres (A23)",
        "file": "common/migrations/postgres/0006_cause_kinds.sql",
        "edits": [
            ("ALTER TABLE hypotheses ADD CONSTRAINT hypotheses_cause_kind_closed\n", "SELECT 1 WHERE false AND\n")
        ],
        "tests": [IT + "test_phase2.py::test_schema_rejects_a_cause_kind_outside_the_closed_list"],
    },
    "contamination_scenario": {
        "property": "Contamination (A25): postmortems of every fixture with the same scenario are excluded",
        "file": "evals/harness.py",
        "edits": [('other["scenario"] == label["scenario"] or _kinds(other) & mine}', "False}")],
        "tests": [U + "test_eval_rules.py::test_related_postmortems_cover_the_scenario_and_shared_kinds"],
    },
    "backend_agreement": {
        "property": "Backend agreement (A26): a tool call whose Parquet rows differ from ClickHouse's is reported",
        "file": "evals/harness.py",
        "edits": [("            elif snap.id != rec.snapshot_id:\n", "            elif False:\n")],
        "tests": [IT + "test_phase2.py::test_backend_agreement_holds_and_catches_a_difference"],
    },
    "backend_agreement_gate": {
        "property": "Backend agreement (A26): any mismatch blocks the eval gate",
        "file": "evals/harness.py",
        "edits": [('    if current.get("backend_mismatches"):\n', "    if False:\n")],
        "tests": [U + "test_eval_rules.py::test_gate_blocks_on_any_backend_mismatch"],
    },
    "leak_scenario": {
        "property": "Leak test (A28): an item only one scenario's faults emit is caught",
        "file": "recorder/leaks.py",
        "edits": [("        if len(scenarios) == 1 and not confounders:\n", "        if False:\n")],
        "tests": [U + "test_leaks.py::test_markers_are_caught_and_shared_vocabulary_is_not"],
    },
    "leak_confounder": {
        "property": "Leak test (A28): an item only a confounder emits is caught",
        "file": "recorder/leaks.py",
        "edits": [("        elif confounders and not scenarios:\n", "        elif False:\n")],
        "tests": [U + "test_leaks.py::test_markers_are_caught_and_shared_vocabulary_is_not"],
    },
    "posthoc_rule": {
        "property": "Post-hoc rule (A27): a baseline change after test results needs a logged amendment",
        "file": "evals/harness.py",
        "edits": [("    return [] if logged else [", "    return [] if True else [")],
        "tests": [U + "test_eval_rules.py::test_a_baseline_change_after_test_results_needs_a_post_hoc_amendment"],
    },
    "alert_baseline_exclusion": {
        "property": "Alert baseline (A29): minutes inside an incident's period are not baseline",
        "file": "alerting/rules.py",
        "edits": [("for m, v in minutes.items() if not any(", "for m, v in minutes.items() if True or not any(")],
        "tests": [
            U + "test_rules.py::test_baseline_minutes_inside_an_incident_period_are_excluded",
            IT + "test_alerting.py::test_a_previous_incident_does_not_hide_a_new_fault_in_the_baseline",
        ],
    },
    "alert_baseline_wiring": {
        "property": "Alert baseline (A29): the engine applies the exclusion to what it reads",
        "file": "alerting/engine.py",
        "edits": [("        per_minute = outside_incidents(per_minute, exclude or [])\n", "")],
        "tests": [IT + "test_alerting.py::test_a_previous_incident_does_not_hide_a_new_fault_in_the_baseline"],
    },
    "recorder_clean_start": {
        "property": "Recorder (A29): no fault starts with an incident in the alert baseline",
        "file": "recorder/record.py",
        "edits": [
            (
                '    return f"{row[0]} incidents in the alert baseline',
                '    return None if True else f"{row[0]} incidents in the alert baseline',
            )
        ],
        "tests": [IT + "test_recorder.py::test_fault_start_is_refused_while_an_incident_lies_in_the_alert_baseline"],
    },
    "eval_db_hash": {
        "property": "Eval read-only (A16): a write to the eval database fails the eval",
        "file": "evals/harness.py",
        "edits": [("    if before != after:\n", "    if False:\n")],
        "tests": [IT + "test_phase2.py::test_eval_fails_when_the_database_changes"],
    },
}
