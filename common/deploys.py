"""Deploy events: the one code path for writing and reading them (Amendment A9).

The injector records them; the fixture recorder and Phase 2's get_recent_deploys read them with
recent(), against the live database or an isolated eval database alike.
"""

from datetime import UTC, datetime
from typing import Any

from clickhouse_connect.driver.client import Client

COLUMNS = ["id", "tenant_id", "service", "version", "started_at", "finished_at"]


def record(ch: Client, deploy: dict[str, Any]) -> None:
    ch.insert("deploys", [[deploy[c] for c in COLUMNS]], column_names=COLUMNS)


def recent(ch: Client, tenant: str, start: datetime, end: datetime, service: str | None = None) -> list[dict[str, Any]]:
    """Deploys of `tenant` (optionally one service) that finished in [start, end], oldest first."""
    rows = ch.query(
        f"SELECT {', '.join(COLUMNS)} FROM deploys WHERE tenant_id = {{t:String}} "
        "AND finished_at >= {s:DateTime64(3)} AND finished_at <= {e:DateTime64(3)} "
        + ("AND service = {svc:String} " if service is not None else "")
        + "ORDER BY finished_at, id LIMIT 1 BY id",
        parameters={"t": tenant, "s": start, "e": end, **({"svc": service} if service is not None else {})},
    ).result_rows
    out = []
    for r in rows:
        d = dict(zip(COLUMNS, r, strict=True))
        for k in ("started_at", "finished_at"):
            if d[k].tzinfo is None:
                d[k] = d[k].replace(tzinfo=UTC)
        out.append(d)
    return out
