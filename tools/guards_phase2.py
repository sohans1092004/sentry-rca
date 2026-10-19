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
        "property": "Contamination rule (§12.2): search_runbooks never returns the evaluated fixture's postmortem",
        "file": "investigation/runbooks.py",
        "edits": [
            (
                "\"AND (fixture_id IS NULL OR fixture_id <> COALESCE(%s, '')) \"",
                "\"AND (fixture_id IS NULL OR fixture_id <> COALESCE(%s, '') OR TRUE) \"",
            )
        ],
        "tests": [IT + "test_phase2.py::test_fixtures_own_postmortem_is_not_returned_by_search_runbooks"],
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
        "property": "Conflict margin (§7.5): an ambiguous fixture reports CONFLICTING_EVIDENCE",
        "file": "investigation/outcome.py",
        "edits": [('        if different and top["score"] - other["score"] <= margin:', "        if False:")],
        "tests": [F + "test_offline_baseline.py::test_ambiguous_fixture_reports_conflicting_evidence"],
    },
    "eval_db_hash": {
        "property": "Eval read-only (A16): a write to the eval database fails the eval",
        "file": "evals/harness.py",
        "edits": [("    if before != after:\n", "    if False:\n")],
        "tests": [IT + "test_phase2.py::test_eval_fails_when_the_database_changes"],
    },
}
