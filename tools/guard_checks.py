"""Remove-the-guard checks: for each safety property, remove its guard, show its test failing,
restore it, show the test passing. Results are appended to tools/guard_checks.out.

    uv run python tools/guard_checks.py [guard ...]     # default: all
"""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "guard_checks.out"

T = "tests/integration/"
GUARDS: dict[str, dict] = {
    "stable_ids": {
        "property": "Stable-ID dedup: the same telemetry delivered twice is one logical row under FINAL",
        "file": "common/ids.py",
        "edits": [
            (
                'return uuid.uuid5(_NAMESPACE, json.dumps(parts, sort_keys=True, separators=(",", ":")))',
                "return uuid.uuid4()",
            )
        ],
        # spans are keyed by their own trace_id/span_id, so only metrics and logs depend on this guard
        "tests": [
            T + "test_processors.py::test_same_telemetry_twice_is_one_logical_row[metrics]",
            T + "test_processors.py::test_same_telemetry_twice_is_one_logical_row[logs]",
        ],
    },
    "validation": {
        "property": "DLQ: malformed payloads land in the right DLQ with a reason; processing continues",
        "file": "processors/convert.py",
        "edits": [("    if not ok:\n        raise Invalid(reason)", "    pass")],
        "tests": [T + "test_processors.py::test_malformed_payloads_go_to_dlq_and_processing_continues"],
    },
    "commit_after_insert": {
        "property": "Commit-after-insert: a kill between insert and commit loses no telemetry",
        "file": "processors/runner.py",
        "edits": [
            ('        _crash_point("between_insert_and_commit")\n        consumer.commit(asynchronous=False)\n', ""),
            (
                "        if rows:\n            _insert(",
                '        _crash_point("between_insert_and_commit")\n        consumer.commit(asynchronous=False)\n'
                "        if rows:\n            _insert(",
            ),
        ],
        "tests": [T + "test_processors.py::test_kill_between_insert_and_commit_loses_nothing"],
    },
    # Two ways to break incident dedup, each failing by visible state, not by an error:
    "incidents_plain_insert": {
        "property": "Incident dedup: N repeated alerts -> one open incident with alert_count = N",
        "file": "alerting/engine.py",
        "edits": [
            (
                "        \"ON CONFLICT (tenant_id, fingerprint) WHERE status <> 'resolved' \"\n"
                '        "DO UPDATE SET last_seen = EXCLUDED.last_seen, alert_count = incidents.alert_count + 1 "\n',
                "",
            )
        ],
        # a plain INSERT needs the index gone too, or it fails with a unique violation instead of duplicating
        "extra": [
            (
                "common/migrations/postgres/0001_init.sql",
                "CREATE UNIQUE INDEX incidents_one_open\n"
                "  ON incidents (tenant_id, fingerprint) WHERE status <> 'resolved';",
                "",
            )
        ],
        "tests": [T + "test_alerting.py::test_repeated_alerts_make_exactly_one_open_incident"],
    },
    "incidents_full_unique_index": {
        "property": "Incident dedup is per open incident: after resolve, a new alert opens a new incident",
        "file": "common/migrations/postgres/0001_init.sql",
        "edits": [
            (
                "  ON incidents (tenant_id, fingerprint) WHERE status <> 'resolved';",
                "  ON incidents (tenant_id, fingerprint);",
            )
        ],
        "tests": [T + "test_alerting.py::test_alert_after_resolve_opens_a_new_incident"],
    },
    "stable_trigger_id": {
        "property": "incidents.opened redelivery is harmless: two publishes -> one downstream event",
        "file": "alerting/engine.py",
        "edits": [('return f"opened:{incident_id}"', 'return f"opened:{incident_id}:{uuid.uuid4()}"')],
        "tests": [T + "test_alerting.py::test_incidents_opened_redelivery_is_one_event_downstream"],
    },
    "metrics_1h_dedup": {
        "property": "metrics_1h: a batch delivered twice is counted once",
        "file": "recorder/downsample.py",
        "edits": [
            # every row its own group: a redelivered copy is counted again
            (
                "  GROUP BY point_id, tenant_id, service, metric  --",
                "  GROUP BY rand(), point_id, tenant_id, service, metric  --",
            )
        ],
        "tests": [T + "test_retention.py::test_metrics_1h_counts_a_twice_delivered_batch_once"],
    },
    "fixture_content_hash": {
        "property": "Fixture round trip: identical row counts and content hashes after load",
        "file": "recorder/load.py",
        "edits": [("    verify_hashes(dataset, ch, database)\n", "")],
        "tests": [T + "test_recorder.py::test_loader_rejects_tampered_dataset"],
    },
}


sys.path.insert(0, str(Path(__file__).resolve().parent))
from guards_phase2 import GUARDS_PHASE2  # noqa: E402
from guards_phase3 import GUARDS_PHASE3  # noqa: E402

GUARDS.update(GUARDS_PHASE2)
GUARDS.update(GUARDS_PHASE3)


def _apply(text: str, edit: tuple, where: str) -> str:
    """An edit is (old, new), or ("require", reason fragment, n): disable the n-th verifier check whose
    line contains the fragment, by turning `_require(cond, ...)` into `_require(True or cond, ...)`."""
    if edit[0] == "require":
        _, fragment, nth = edit
        lines = text.splitlines(keepends=True)
        hits = [i for i, ln in enumerate(lines) if "_require(" in ln and fragment in ln]
        assert len(hits) > nth, f"{where}: no _require line #{nth} containing {fragment!r}"
        lines[hits[nth]] = lines[hits[nth]].replace("_require(", "_require(True or ", 1)
        return "".join(lines)
    old, new = edit
    assert text.count(old) == 1, f"{where}: guard text not found exactly once"
    return text.replace(old, new)


def pytest(tests: list[str]) -> tuple[int, str]:
    cmd = ["uv", "run", "pytest", "-vv", "-p", "no:cacheprovider", *tests]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    lines = (p.stdout + p.stderr).strip().splitlines()
    errors = [ln for ln in lines if ln.startswith("E ")][:8]  # the failing assertion, with its values
    summary = "\n".join(errors + lines[-1:])
    return p.returncode, f"$ {' '.join(cmd)}\n{summary}"


def check(name: str) -> bool:
    g = GUARDS[name]
    changes = [(g["file"], *e) for e in g["edits"]] + list(g.get("extra", []))
    originals = {f: (ROOT / f).read_bytes() for f, *_ in changes}
    # working copies on Windows may be CRLF; git stores LF, so match and write LF
    texts = {f: b.decode().replace("\r\n", "\n") for f, b in originals.items()}
    for f, *edit in changes:
        texts[f] = _apply(texts[f], tuple(edit), f"{name} in {f}")
    try:
        for f, t in texts.items():
            (ROOT / f).write_bytes(t.encode())
        removed_rc, removed_out = pytest(g["tests"])
    finally:
        for f, b in originals.items():
            (ROOT / f).write_bytes(b)
    restored_rc, restored_out = pytest(g["tests"])
    ok = removed_rc != 0 and restored_rc == 0
    report = (
        f"=== {name} @ {datetime.now(UTC).isoformat(timespec='seconds')} -> {'PASS' if ok else 'FAIL'}\n"
        f"property: {g['property']}\nguard removed in {g['file']}: {g['edits']!r}\n"
        f"--- guard removed (expect failure, exit {removed_rc}):\n{removed_out}\n"
        f"--- guard restored (expect pass, exit {restored_rc}):\n{restored_out}\n\n"
    )
    with OUT.open("a", encoding="utf-8") as f:
        f.write(report)
    print(report)
    return ok


if __name__ == "__main__":
    names = sys.argv[1:] or list(GUARDS)
    results = {n: check(n) for n in names}
    print(results)
    sys.exit(0 if all(results.values()) else 1)
