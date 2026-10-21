"""Write one postmortem per DEV fixture into runbooks/postmortems/fixtures/, tagged with its fixture_id.

These contain the answer, which is the point: SPEC §12.2 / A25 exclude every postmortem of the same
scenario while a fixture is evaluated, and the contamination guard proves it. Test fixtures get none
(A25): their scenarios must not reach the corpus. The text describes the v3 fault mechanisms in the
words the services log (A21), as a postmortem written after the incident would.

    uv run python tools/write_fixture_postmortems.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "runbooks" / "postmortems" / "fixtures"
VERSION = "v3"


def cause(step: dict) -> str:
    k, p, svc = step["kind"], step["params"], step["service"]
    if k == "bad_deploy":
        if p["mode"] == "errors":
            return (f"the deploy of {p['version']} to {svc} shipped a regression: about {p['error_rate']:.0%} of "
                    "requests failed with unhandled exceptions "
                    "('Exception in ASGI application: KeyError')")  # fmt: skip
        slow = f"added about {p['delay_ms']} ms to every request"
        return f"the deploy of {p['version']} to {svc} shipped a regression that {slow}"
    if k == "lock_wait":
        where = f"{p['op']} statements on the {p['table']} table in {svc}"
        return (f"{where} waited on a lock for about {p['delay_ms']} ms each; the slow-statement log "
                "('duration: ... statement: ...') rose sharply")  # fmt: skip
    if k == "conn_leak":
        return (f"a code path in {svc} leaked database connections; the pool of 10 filled, acquires timed out "
                "('QueuePool limit of size 10 ... connection timed out') and payments retried hold confirmations, "
                "multiplying the load")  # fmt: skip
    if k == "dependency_outage":
        return ("the external payment provider timed out for most charges from payments; retries "
                "('provider charge failed ... retrying: timed out') multiplied the slow calls")  # fmt: skip
    if k == "memory_leak":
        return f"an unbounded in-process cache in {svc} grew without limit; memory rose and every request slowed"
    if k == "cpu_burn":
        return "a CPU-heavy batch job on the core shared with payments and inventory starved both of CPU"
    raise ValueError(k)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()
    for d in sorted((ROOT / "fixtures").iterdir()):
        label_path = d / VERSION / "label.json"
        if not label_path.exists():
            continue
        label = json.loads(label_path.read_text())
        if label.get("split") != "dev":
            continue
        inj = json.loads((d / VERSION / "injection.json").read_text())
        steps = [a for a in inj["run"]["applied"] if a["role"] == "cause"]
        if label["root_cause"] is None:
            what = ("there was no single cause: every service showed small random latency at once (background "
                    "noise), and no deploy, error or dependency explained it")  # fmt: skip
        else:
            seen, parts = set(), []
            for s in steps:  # one line per distinct fault (connection_refused-style steps repeat per caller)
                if (key := (s["kind"], s["service"])) not in seen:
                    seen.add(key)
                    parts.append(cause(s))
            what = parts[0] + (f"; at the same time, {parts[1]}" if len(parts) > 1 else "")
        conf = [c for c in label.get("confounders", []) if c["kind"] == "deploy"]
        noise = f" A deploy to {conf[0]['service']} shortly before was unrelated." if conf else ""
        symptoms = ", ".join(label["symptom_services"]) or "none beyond the edge"
        body = (
            f"Incident on {inj['incident']['service']}, alert {inj['alert_latency_s']:.0f} s after the fault began.\n"
            f"Root cause: {what}.{noise}\n"
            f"Symptoms: {symptoms} slowed or failed as a result.\n"
            "Resolution: the fault was removed and the incident resolved on its own."
        )
        title = f"Postmortem: {label['scenario'].replace('_', ' ')} incident ({label['fixture_id']})"
        (OUT / f"{label['fixture_id']}.md").write_text(
            f"title: {title}\nkind: postmortem\nfixture_id: {label['fixture_id']}\n---\n{body}\n", encoding="utf-8"
        )
    print(len(list(OUT.glob("*.md"))), "fixture postmortems")


if __name__ == "__main__":
    main()
