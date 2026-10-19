"""One ranker over one investigation: tool layer -> ranked hypotheses -> verification -> outcome.
Shared by the orchestrator (Postgres store, ClickHouse backend) and offline runs (memory store,
Parquet backend)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from investigation import baseline, outcome, verifier
from investigation.backend import Backend
from investigation.scope import Scope
from investigation.tools import RunbookIndex, Store, ToolLayer

Ranker = Callable[..., list[dict[str, Any]]]


@dataclass
class RankerResult:
    hypotheses: list[dict[str, Any]]
    verification: list[verifier.HypothesisResult]
    outcome: str
    tool_calls: int

    @property
    def verified(self) -> list[dict[str, Any]]:
        return [h for h, v in zip(self.hypotheses, self.verification, strict=True) if v.passed]


def run_ranker(
    store: Store,
    backend: Backend,
    runbooks: RunbookIndex | None,
    investigation_id: str,
    scope: Scope,
    ranker: str = "baseline",
    rank: Ranker = baseline.rank,
) -> RankerResult:
    layer = ToolLayer(store, backend, runbooks, investigation_id, scope, ranker)
    hypotheses = rank(scope, layer.call, runbook_search=runbooks is not None)
    calls = store.calls(investigation_id)
    results = [verifier.verify(h, calls, ranker, scope.excluded()) for h in hypotheses]
    verified = [h for h, v in zip(hypotheses, results, strict=True) if v.passed]
    return RankerResult(hypotheses, results, outcome.decide(verified), layer.issued)
