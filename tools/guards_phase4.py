"""Phase 4 remove-the-guard checks for the static viewer (SPEC §11). Each removal must make its test
fail by showing the unsafe behaviour: recorded telemetry parsed into page markup, or an inline script
running on a page with no CSP."""

V = "tests/viewer/test_viewer_xss.py::"

GUARDS_PHASE4: dict[str, dict] = {
    "viewer_text_only": {
        "property": "Viewer: recorded telemetry reaches the page only as text, never as markup",
        "file": "viewer/app.js",
        "edits": [
            (
                '  return document.createTextNode(typeof v === "string" ? v : JSON.stringify(v));',
                '  const s = document.createElement("span");\n  s.innerHTML = typeof v === "string" ? v : JSON.stringify(v);\n  return s;',
            )
        ],
        "tests": [V + "test_a_script_payload_in_recorded_telemetry_never_executes_in_the_viewer"],
    },
    "viewer_csp": {
        "property": "Viewer: the strict CSP blocks inline script",
        "file": "viewer/index.html",
        "edits": [
            (
                "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'\">\n",
                "",
            )
        ],
        "tests": [V + "test_the_viewer_csp_blocks_inline_script"],
    },
}
