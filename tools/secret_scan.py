"""Fail if a key-shaped secret is in the repository or in recorded LLM data (cassettes, embeddings).

Scans every tracked file plus `evals/cassettes/` (tracked or not). Patterns cover the provider keys this
project could plausibly hold. The hosted provider puts its key only in an HTTP header and never in a
request body, so no recorded exchange should ever contain one.

    uv run python tools/secret_scan.py      # exit 1 and list file:line on any match
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "google_api_key_v2": re.compile(r"\bAQ\.[0-9A-Za-z_\-]{40,}"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    "groq_key": re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "bearer_literal": re.compile(r"Bearer [A-Za-z0-9._\-]{20,}"),
}


def files() -> list[Path]:
    tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT).stdout.splitlines()
    out = {ROOT / f for f in tracked}
    out |= {p for p in (ROOT / "evals" / "cassettes").rglob("*") if p.is_file()}
    return sorted(p for p in out if p.is_file())


def scan(paths: list[Path]) -> list[tuple[str, int, str]]:
    """(file, line, pattern name) for every match; the matched text itself is never returned."""
    hits = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for name, rx in PATTERNS.items():
                if rx.search(line):
                    hits.append((str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p), n, name))
    return hits


if __name__ == "__main__":
    found = scan(files())
    for f, n, name in found:
        print(f"SECRET? {f}:{n} looks like {name}")
    print(f"{len(files())} files scanned, {len(found)} key-shaped strings")
    sys.exit(1 if found else 0)
