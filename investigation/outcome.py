"""Outcome rules (SPEC §7.5), over verified hypotheses only."""

from typing import Any

CONFLICT_MARGIN = 0.1


def decide(verified: list[dict[str, Any]], margin: float = CONFLICT_MARGIN) -> str:
    roots = sorted((h for h in verified if h["causal_role"] == "candidate_root_cause"),
                   key=lambda h: (-h["score"], h["cause_service"], h["cause_kind"]))  # fmt: skip
    if not roots:
        return "INSUFFICIENT_EVIDENCE"
    top = roots[0]
    for other in roots[1:]:
        different = (other["cause_service"], other["cause_kind"]) != (top["cause_service"], top["cause_kind"])
        if different and top["score"] - other["score"] <= margin:
            return "CONFLICTING_EVIDENCE"
    return "ROOT_CAUSE_IDENTIFIED"
