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
    "incidents_one_open": {
        "property": "Incident dedup: N repeated alerts -> one open incident with alert_count = N",
        "file": "common/migrations/postgres/0001_init.sql",
        "edits": [
            (
                "CREATE UNIQUE INDEX incidents_one_open\n"
                "  ON incidents (tenant_id, fingerprint) WHERE status <> 'resolved';",
                "",
            )
        ],
        "tests": [T + "test_alerting.py::test_repeated_alerts_dedup_into_one_incident_until_resolved"],
    },
    "stable_trigger_id": {
        "property": "incidents.opened redelivery is harmless: two publishes -> one downstream event",
        "file": "alerting/engine.py",
        "edits": [('return f"opened:{incident_id}"', 'return f"opened:{incident_id}:{uuid.uuid4()}"')],
        "tests": [T + "test_alerting.py::test_incidents_opened_redelivery_is_one_event_downstream"],
    },
    "fixture_content_hash": {
        "property": "Fixture round trip: identical row counts and content hashes after load",
        "file": "recorder/load.py",
        "edits": [("    verify_hashes(dataset, client)\n", "")],
        "tests": [T + "test_recorder.py::test_loader_rejects_tampered_dataset"],
    },
}


def pytest(tests: list[str]) -> tuple[int, str]:
    cmd = ["uv", "run", "pytest", "-q", "-p", "no:cacheprovider", *tests]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    lines = (p.stdout + p.stderr).strip().splitlines()
    summary = "\n".join(lines[-6:])
    return p.returncode, f"$ {' '.join(cmd)}\n{summary}"


def check(name: str) -> bool:
    g = GUARDS[name]
    path = ROOT / g["file"]
    original = path.read_bytes()
    text = original.decode()
    for old, new in g["edits"]:
        assert text.count(old) == 1, f"{name}: guard text not found exactly once in {g['file']}"
        text = text.replace(old, new)
    try:
        path.write_bytes(text.encode())
        removed_rc, removed_out = pytest(g["tests"])
    finally:
        path.write_bytes(original)
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
