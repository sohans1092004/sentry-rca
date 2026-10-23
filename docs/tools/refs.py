"""Builds the cited documents and checks every reference in them (the Concord tool, for this repository).

  uv run python docs/tools/refs.py build   # docs/src/<doc>/*.md -> docs/<doc>.md (references resolved)
  uv run python docs/tools/refs.py check   # every file:line, commit and test name in the docs resolves

In a source file, [[alias#anchor]] cites the first line of the file that contains `anchor` (build fails if
it is missing or not unique), and [[alias#anchor..end]] a range ending at the first line after it that
contains `end`. Each renders as a link `file.py:N` to that line, and docs/refs.json records the anchor, so
`check` can tell when the code has moved under a citation. [[<commit>:path#anchor]] cites the file as it
was at that commit (code that no longer exists, such as the Phase 2 fault messages), read with `git show`
and linked on GitHub at that commit. Mermaid blocks stay inline: GitHub renders them.
"""

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
SRC = DOCS / "src"
REFS = DOCS / "refs.json"
OUTPUTS = ["how-sentry-rca-was-built.md", "interview-guide.md"]
GITHUB = "https://github.com/sohans1092004/sentry-rca/blob"

ALIASES = {
    "agent": "investigation/agent.py",
    "llm": "investigation/llm.py",
    "orch": "investigation/orchestrator.py",
    "verifier": "investigation/verifier.py",
    "baseline": "investigation/baseline.py",
    "tools": "investigation/tools.py",
    "scope": "investigation/scope.py",
    "snapshots": "investigation/snapshots.py",
    "timeline": "investigation/timeline.py",
    "outcome": "investigation/outcome.py",
    "run": "investigation/run.py",
    "runbooks": "investigation/runbooks.py",
    "cli": "investigation/cli.py",
    "backend": "investigation/backend.py",
    "harness": "evals/harness.py",
    "kinds": "common/kinds.py",
    "engine": "alerting/engine.py",
    "faults": "services/faults.py",
    "demodb": "services/demo_db.py",
    "base": "services/base.py",
    "scenarios": "injector/scenarios.py",
    "record": "recorder/record.py",
    "gold": "recorder/gold.py",
    "leaks": "recorder/leaks.py",
    "pg4": "common/migrations/postgres/0004_investigation.sql",
    "pg7": "common/migrations/postgres/0007_llm_exchanges.sql",
    "guards": "tools/guard_checks.py",
    "guards2": "tools/guards_phase2.py",
    "guards3": "tools/guards_phase3.py",
    "guards4": "tools/guards_phase4.py",
    "secretscan": "tools/secret_scan.py",
    "export": "tools/export_viewer.py",
    "app": "viewer/app.js",
    "xss": "tests/viewer/test_viewer_xss.py",
    "spec": "docs/SPEC.md",
    "ci": ".github/workflows/ci.yml",
}

REF = re.compile(r"\[\[([^\]#]+)#([^\]]+?)\]\]")
LINK = re.compile(r"\[`([^`]+):(\d+)(?:-(\d+))?`\]\(((?:\.\./)+[^)#]+)#L(\d+)(?:-L(\d+))?\)")
HIST = re.compile(r"\[`[^`]+`\]\(" + re.escape(GITHUB) + r"/([0-9a-f]{40})/([^)#]+)#L(\d+)(?:-L(\d+))?\)")


def path_of(alias: str) -> str:
    return ALIASES.get(alias.strip(), alias.strip())


def git_text(sha: str, rel: str) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"{sha}:{rel}"], capture_output=True, text=True,
                       encoding="utf-8")  # fmt: skip
    if r.returncode != 0:
        raise SystemExit(f"no {rel} at {sha}")
    return r.stdout


def full_sha(sha: str) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", f"{sha}^{{commit}}"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"no commit {sha}")
    return r.stdout.strip()


def find(lines: list[str], anchor: str, start: int, rel: str) -> int:
    hits = [i for i in range(start, len(lines)) if anchor in lines[i]]
    if not hits:
        raise SystemExit(f"anchor not found in {rel}: {anchor!r}")
    if start == 0 and len(hits) > 1:
        raise SystemExit(f"anchor not unique in {rel} ({len(hits)} lines): {anchor!r}")
    return hits[0]


def build() -> None:
    refs: dict[str, dict[str, str]] = {}
    cache: dict[str, list[str]] = {}  # file lines, shared by both documents
    for name in OUTPUTS:
        parts = SRC / name[:-3]  # a long document is a directory of parts, joined in name order
        if not parts.is_dir():
            continue
        text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(parts.glob("*.md")))

        def resolve(m: re.Match[str]) -> str:
            target, anchor_spec = m.group(1).strip(), m.group(2)
            sha = None
            if re.match(r"^[0-9a-f]{7,40}:", target):
                short, rel = target.split(":", 1)
                sha = full_sha(short)
                rel = path_of(rel)
                lines = cache.setdefault(f"{sha}:{rel}", git_text(sha, rel).splitlines())
            else:
                rel = path_of(target)
                f = ROOT / rel
                if not f.is_file():
                    raise SystemExit(f"no such file: {rel}")
                lines = cache.setdefault(rel, f.read_text(encoding="utf-8").splitlines())
            anchor, _, end = anchor_spec.partition("..")
            a = find(lines, anchor, 0, rel)
            b = find(lines, end, a + 1, rel) if end else a
            span = f"{a + 1}" + (f"-{b + 1}" if end else "")
            frag = f"#L{a + 1}" + (f"-L{b + 1}" if end else "")
            key = f"{sha}:{rel}" if sha else rel
            refs[f"{key}#L{a + 1}"] = {"anchor": anchor}
            if end:
                refs[f"{key}#L{b + 1}"] = {"anchor": end}
            label = pathlib.PurePosixPath(rel).name
            if sha:
                return f"[`{label}:{span} @{sha[:7]}`]({GITHUB}/{sha}/{rel}{frag})"
            return f"[`{label}:{span}`](../{rel}{frag})"

        text = REF.sub(resolve, text)
        (DOCS / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"built docs/{name}")
    REFS.write_text(json.dumps(refs, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def check() -> None:
    refs = json.loads(REFS.read_text(encoding="utf-8")) if REFS.exists() else {}
    files = lines = shas = tests = 0
    bad: list[str] = []
    known_tests = {
        m.group(1)
        for f in (ROOT / "tests").rglob("test_*.py")
        for m in re.finditer(r"^def (test_[a-z0-9_]+)\(", f.read_text(encoding="utf-8"), re.M)
    }

    def check_line(name: str, key: str, src: list[str], line: int) -> None:
        nonlocal lines
        lines += 1
        if line > len(src) or not src[line - 1].strip():
            bad.append(f"{name}: {key}:{line} is past the end or blank")
            return
        want = refs.get(f"{key}#L{line}")
        if want and want["anchor"] not in src[line - 1]:
            bad.append(f"{name}: {key}:{line} no longer contains {want['anchor']!r}")
        elif not want:
            bad.append(f"{name}: {key}:{line} has no recorded anchor (cited by hand?)")

    for name in OUTPUTS:
        if not (DOCS / name).exists():
            bad.append(f"{name}: not built")
            continue
        text = (DOCS / name).read_text(encoding="utf-8")
        for m in LINK.finditer(text):
            rel = re.sub(r"^(\.\./)+", "", m.group(4))
            files += 1
            f = ROOT / rel
            if not f.is_file():
                bad.append(f"{name}: missing file {rel}")
                continue
            src = f.read_text(encoding="utf-8").splitlines()
            for line in [int(m.group(5))] + ([int(m.group(6))] if m.group(6) else []):
                check_line(name, rel, src, line)
        for m in HIST.finditer(text):
            sha, rel = m.group(1), m.group(2)
            files += 1
            src = git_text(sha, rel).splitlines()
            for line in [int(m.group(3))] + ([int(m.group(4))] if m.group(4) else []):
                check_line(name, f"{sha}:{rel}", src, line)
        # Hand-written references outside links (a repo path with a slash): the file and lines must exist.
        plain = HIST.sub("", LINK.sub("", text))
        for m in re.finditer(r"([\w.-]+(?:/[\w.-]+)+\.(?:md|py|js|sql|yml|yaml|json|txt|csv|html|css)):(\d+)", plain):
            f = ROOT / m.group(1)
            files += 1
            lines += 1
            if not f.is_file():
                bad.append(f"{name}: missing file {m.group(1)}")
            elif int(m.group(2)) > len(f.read_text(encoding="utf-8").splitlines()):
                bad.append(f"{name}: {m.group(1)}:{m.group(2)} is past the end")
        # Paths named without a line must exist too.
        for m in re.finditer(r"`((?:[\w.-]+/)+[\w.-]+\.(?:md|py|js|sql|yml|json|txt|csv|html|css|out|ps1))`", plain):
            files += 1
            if not (ROOT / m.group(1)).is_file():
                bad.append(f"{name}: missing file {m.group(1)}")
        for m in re.finditer(r"`([0-9a-f]{7,40})`", text):
            shas += 1
            r = subprocess.run(
                ["git", "-C", str(ROOT), "cat-file", "-e", m.group(1) + "^{commit}"], capture_output=True
            )
            if r.returncode != 0:
                bad.append(f"{name}: commit {m.group(1)} not found")
        for m in re.finditer(r"`(test_[a-z0-9_]+)`", text):
            tests += 1
            if m.group(1) not in known_tests:
                bad.append(f"{name}: test {m.group(1)} not found")
    print(f"checked {files} file references ({lines} line numbers), {shas} commit SHAs, {tests} test names")
    for b in bad:
        print("  FAIL", b)
    print("all references resolve" if not bad else f"{len(bad)} problems")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    {"build": build, "check": check}[sys.argv[1] if len(sys.argv) > 1 else "check"]()
