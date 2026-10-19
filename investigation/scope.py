"""Investigation scope (SPEC §5.2), computed once per investigation and stored in investigations.scope.

- Tenant: from the incident row; every query is filtered by it, no argument can change it.
- Services: the incident's service plus every service within `depth` hops in the undirected
  dependency graph from service_edges over the last 24 h plus the incident window.
- Window: first_anomaly_at - 30 min .. last_seen + 15 min, intersected with `clamp` when a fixture
  only holds a shorter window (A7).
- Caps: 500 rows and 256 KB per result.
"""

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from investigation.backend import Backend

DEPTH = 2
BEFORE, AFTER = timedelta(minutes=30), timedelta(minutes=15)
GRAPH_LOOKBACK = timedelta(hours=24)
MAX_ROWS, MAX_BYTES, MAX_TOP_K = 500, 262_144, 20


def iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse(t: str) -> datetime:
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    incident_service: str
    services: tuple[str, ...]
    start: datetime
    end: datetime
    depth: int = DEPTH
    max_rows: int = MAX_ROWS
    max_bytes: int = MAX_BYTES
    excluded_fixture: str | None = None  # SPEC §12.2: this fixture's postmortems are never returned

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["services"], d["start"], d["end"] = list(self.services), iso(self.start), iso(self.end)
        return d

    @staticmethod
    def from_json(d: dict[str, Any]) -> "Scope":
        return Scope(**{**d, "services": tuple(d["services"]), "start": parse(d["start"]), "end": parse(d["end"])})


def allowed_services(edges: list[tuple[str, str, int]], root: str, depth: int) -> tuple[str, ...]:
    graph: dict[str, set[str]] = defaultdict(set)
    for parent, child, _ in edges:
        graph[parent].add(child)
        graph[child].add(parent)
    seen = {root: 0}
    queue = deque([root])
    while queue:
        node = queue.popleft()
        if seen[node] == depth:
            continue
        for nxt in sorted(graph[node]):
            if nxt not in seen:
                seen[nxt] = seen[node] + 1
                queue.append(nxt)
    return tuple(sorted(seen))


def compute(backend: Backend, incident: dict[str, Any], *, depth: int = DEPTH,
            clamp: tuple[datetime, datetime] | None = None, excluded_fixture: str | None = None) -> Scope:  # fmt: skip
    start, end = incident["first_anomaly_at"] - BEFORE, incident["last_seen"] + AFTER
    if clamp is not None:
        start, end = max(start, clamp[0]), min(end, clamp[1])
    edges = backend.edges(str(incident["tenant_id"]), start - GRAPH_LOOKBACK, end)
    services = allowed_services(edges, incident["service"], depth)
    return Scope(str(incident["tenant_id"]), incident["service"], services, start, end, depth,
                 excluded_fixture=excluded_fixture)  # fmt: skip
