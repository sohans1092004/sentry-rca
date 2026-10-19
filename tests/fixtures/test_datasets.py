"""Every published fixture dataset: content hashes match its manifest, its label is well formed, and
one loads into an isolated ClickHouse database. Needs the datasets: `uv run python tools/fetch_fixtures.py`."""

import json
import uuid
from pathlib import Path

import pytest

from recorder.dataset import TABLES, content_hash, read_parquet

ROOT = Path(__file__).resolve().parents[2]
INDEX = json.loads((ROOT / "fixtures" / "index.json").read_text())
FIXTURES = [a["fixture_id"] for a in INDEX["fixtures"]]
LABEL_KEYS = {"fixture_id", "scenario", "root_cause", "acceptable_alternatives", "symptom_services",
              "expected_outcome", "planted_injection", "gold_claims"}  # fmt: skip
OUTCOMES = {"ROOT_CAUSE_IDENTIFIED", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"}


def dataset(fid: str) -> Path:
    d = ROOT / "data" / "fixtures" / fid / "v1"
    assert (d / "manifest.json").exists(), f"{fid} not present: run `uv run python tools/fetch_fixtures.py`"
    return d


@pytest.mark.parametrize("fid", FIXTURES)
def test_content_hashes_match_manifest(fid):
    d = dataset(fid)
    manifest = json.loads((d / "manifest.json").read_text())
    for table, expected in manifest["tables"].items():
        rows = read_parquet(d / f"{table}.parquet")
        assert {"rows": len(rows), "sha256": content_hash(rows, TABLES[table]["schema"].names)} == expected, table


@pytest.mark.parametrize("fid", FIXTURES)
def test_label_is_well_formed(fid):
    label = json.loads((dataset(fid) / "label.json").read_text())
    assert LABEL_KEYS <= set(label) <= LABEL_KEYS | {"notes"}
    assert label["fixture_id"] == fid and label["expected_outcome"] in OUTCOMES
    assert label["gold_claims"], "every fixture has at least one gold claim"
    assert len({json.dumps(c, sort_keys=True) for c in label["gold_claims"]}) == len(label["gold_claims"])
    if label["scenario"] == "noisy_neighbor":
        assert label["expected_outcome"] == "INSUFFICIENT_EVIDENCE" and "no trace edges" in label["notes"]
    if label["acceptable_alternatives"]:
        assert label["expected_outcome"] == "CONFLICTING_EVIDENCE"
    # the label committed under fixtures/ is the dataset's own copy
    assert label == json.loads((ROOT / "fixtures" / fid / "v1" / "label.json").read_text())


@pytest.mark.integration
def test_smallest_fixture_loads_into_an_isolated_database(ch_container):
    from recorder.load import load
    from tests.integration.conftest import ch_client

    smallest = min(INDEX["fixtures"], key=lambda a: a["bytes"])["fixture_id"]
    load(dataset(smallest), ch_client(ch_container), f"fx_{uuid.uuid4().hex[:8]}")  # raises on any mismatch
