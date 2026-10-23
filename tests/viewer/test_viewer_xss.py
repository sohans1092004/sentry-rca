"""The static viewer renders attacker-controlled telemetry (SPEC §11): a script payload planted in a log
line, a narrative or any other recorded field must never execute, and must never even become markup.

Runs the real viewer in headless Chromium (`uv run playwright install chromium` once) over a synthetic
export whose every string field carries payloads. The CSP is checked separately: an inline script added
to the page must be blocked.
"""

import functools
import http.server
import json
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, sync_playwright

VIEWER = Path(__file__).resolve().parents[2] / "viewer"
SNAP = "a" * 64
TIMELINE = "b" * 64
PAYLOADS = [
    "<script>window.__xss=1</script>",
    '<img src=x onerror="window.__xss=2">',
    '"><svg onload="window.__xss=3">',
    '</pre><iframe src="javascript:window.parent.__xss=4"></iframe>',
]
EVIL = " ".join(PAYLOADS)
FID = "xss_fixture"
PROBE = (
    "window.__csp = [];"
    "document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective));"
)


def site(root: Path) -> None:
    shutil.copytree(VIEWER, root, dirs_exist_ok=True)
    data = root / "data"
    (data / "inv").mkdir(parents=True)
    (data / "snap").mkdir()
    rank1 = [EVIL, EVIL]
    split = {
        "fixtures": 1,
        **{k: {"mean": 0.5} for k in ("top1", "top1_exact", "top1_service", "top3")},
        "confusion": {"ROOT_CAUSE_IDENTIFIED": {"ROOT_CAUSE_IDENTIFIED": 1}},
        "clean": {"fixtures": 1, "top1": {"mean": 1.0}},
        "confounded": {"fixtures": 0, "top1": {"mean": None}},
        "agent": {"outcome_correct": 1, "tokens": {"median": 1000, "max": 2000}, "degraded": 0, "parse_failures": 0},
        "paired": {
            "per_fixture": {
                FID: {
                    "top1": {"verdict": EVIL},
                    "outcome": {"verdict": "tie"},
                    "agent_rank1": [rank1],
                    "baseline_rank1": [rank1],
                }
            },  # fmt: skip
            "top1_tally": {"win": 0, "loss": 0, "tie": 1},
            "top1_sign_test_p": None,
        },
        "rejections_agent": {"hypotheses": {"passed": 1, "rejected": 1}, "failed_claims_by_type": {EVIL: {EVIL: 1}}},
        "gold_rejected": 0,
    }
    split["baseline_same_investigations"] = {**split}
    meta = {"eval_run_id": EVIL, "git_sha": "0123456789abcdef", "model": EVIL, "budget": {EVIL: EVIL}}
    (data / "eval.json").write_text(json.dumps({**meta, "splits": {"test": split}}), encoding="utf-8")
    index = {"fixture": FID, "split": "test", "expected": "ROOT_CAUSE_IDENTIFIED", "outcome": EVIL,
             "agent_rank1": rank1, "baseline_rank1": rank1, "top1": EVIL, "showcase": EVIL}  # fmt: skip
    (data / "index.json").write_text(json.dumps({**meta, "investigations": [index]}), encoding="utf-8")
    call = {"seq": 1, "ranker": "agent", "tool": EVIL, "args": {EVIL: EVIL}, "decision": EVIL, "reason": EVIL,
            "snapshot": SNAP, "rows": 2, "bytes": 10, "ms": 1}  # fmt: skip
    claim = {"type": EVIL, "params": {EVIL: EVIL}, "result": "failed", "reason": EVIL,
             "cites": [{"seq": 1, "row_ids": ["r1"]}]}  # fmt: skip
    hyp: dict[str, Any] = {"rank": 1, "role": EVIL, "service": EVIL, "kind": EVIL, "score": 0.5, "status": EVIL,
                           "narrative": EVIL, "claims": [claim]}  # fmt: skip
    inv = {
        "fixture": FID, "investigation_id": EVIL, "showcase": EVIL, "status": EVIL, "outcome": EVIL,
        "shown_ranker": EVIL, "results": {"agent": EVIL, "baseline": EVIL},
        "label": {"scenario": EVIL, "root_cause": {"service": EVIL, "cause_kind": EVIL}, "split": EVIL,
                  "expected_outcome": EVIL, "notes": EVIL, "planted_injection": True, "planted_row_ids": ["r2"],
                  "confounders": [{"kind": EVIL, "service": EVIL}],
                  "out_of_scope_evidence": [{"type": EVIL, "service": EVIL, "metric": EVIL, "reason": EVIL}]},
        "incident": {"service": EVIL, "first_anomaly_at": EVIL},
        "scope": {"services": [EVIL], "start": EVIL, "end": EVIL},
        "budget": {"agent": {"tool_calls": EVIL, "tokens_in": 1, "tokens_out": 1, "repairs": EVIL}},
        "llm_exchanges": EVIL, "model_ms": 1000, "tool_calls": [call],
        "hypotheses": [{**hyp, "ranker": "baseline"}, {**hyp, "ranker": "agent"}],
        "scope_rejections": [call], "planted_in_agent_results": [1], "timeline_snapshot": TIMELINE,
    }  # fmt: skip
    (data / "inv" / f"{FID}.json").write_text(json.dumps(inv), encoding="utf-8")
    rows = [
        {"row_id": "r1", "ts": EVIL, "service": EVIL, "severity": "ERROR", "body": EVIL, "attrs": {EVIL: EVIL}},
        {"row_id": "r2", "ts": EVIL, "service": EVIL, "severity": "ERROR", "body": EVIL, "attrs": [EVIL]},
        {"row_id": "r3", "ts": EVIL, "service": EVIL, "severity": "INFO", "body": EVIL, "attrs": {}},
    ]
    for sid in (SNAP, TIMELINE):
        body = {"id": sid, "truncated": False, "rows": [{**r, "kind": EVIL} for r in rows]}
        (data / "snap" / f"{sid}.json").write_text(json.dumps(body), encoding="utf-8")


@pytest.fixture(scope="module")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    root = tmp_path_factory.mktemp("site")
    site(root)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None  # type: ignore[attr-defined]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def visit(page: Page, url: str) -> None:
    page.goto(url)
    page.wait_for_load_state("networkidle")


def assert_inert(page: Page, dialogs: list[str], errors: list[str]) -> None:
    executed = page.evaluate("window.__xss")
    blocked = page.evaluate("window.__csp")
    injected = page.evaluate(
        "[...document.querySelectorAll('img, svg, iframe, object, embed, script:not([src])')].length"
        " + [...document.querySelectorAll('*')]"
        ".filter(e => [...e.attributes].some(a => a.name.startsWith('on'))).length"
    )
    assert executed is None, f"payload executed: window.__xss = {executed}"
    assert dialogs == [], f"payload opened a dialog: {dialogs}"
    assert injected == 0, (
        f"{injected} elements were parsed from telemetry text; CSP blocked {len(blocked)}: {sorted(set(blocked))}"
    )
    assert blocked == [], f"telemetry text became markup that the CSP had to block: {blocked}"
    assert errors == [], errors
    assert PAYLOADS[1] in page.inner_text("body"), "the payload must be shown as text"


@pytest.mark.parametrize("path", ["index.html", "eval.html", f"investigation.html?f={FID}"])
def test_a_script_payload_in_recorded_telemetry_never_executes_in_the_viewer(
    browser: Any, base_url: str, path: str
) -> None:
    page = browser.new_page()
    dialogs: list[str] = []
    errors: list[str] = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(PROBE)
    visit(page, base_url + path)
    if path.startswith("investigation"):
        for i in range(page.locator("button.cite").count()):  # open every citation, then show all rows
            page.locator("button.cite").nth(i).click()
            page.wait_for_timeout(300)
        page.get_by_text("Show all").click()
        page.wait_for_timeout(300)
        assert page.locator("#evidence tr.cited").count() == 1
    assert_inert(page, dialogs, errors)
    page.close()


def test_the_viewer_csp_blocks_inline_script(browser: Any, base_url: str) -> None:
    page = browser.new_page()
    visit(page, base_url + "index.html")
    page.evaluate("const s = document.createElement('script'); s.textContent = 'window.__inline = 1'; "
                  "document.body.append(s)")  # fmt: skip
    page.wait_for_timeout(200)
    assert page.evaluate("window.__inline") is None, "an inline script ran: the page has no effective CSP"
    page.close()
