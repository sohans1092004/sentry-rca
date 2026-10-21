"""No key-shaped secret in the repository or in recorded LLM data (cassettes, embeddings). The planted
keys below are assembled at run time, so this file itself holds none."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import secret_scan  # noqa: E402

FAKE = {
    "google_api_key": "AI" + "za" + "Sy" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7",
    "google_api_key_v2": "AQ" + ".Ab8RN" + "x" * 46,
    "openai_key": "sk" + "-proj-" + "a1B2" * 8,
    "bearer_literal": "Bear" + "er " + "eyJ" + "x" * 30,
}


def test_a_planted_key_in_a_cassette_is_found_without_echoing_it(tmp_path):
    cassette = tmp_path / "fixture.json"
    entry = {"response": {"content": f"leak {FAKE['google_api_key_v2']}"}, "request": {"auth": FAKE["bearer_literal"]}}
    cassette.write_text(json.dumps({"model": "m", "digest": "d", "entries": {"k": entry}}, indent=1))
    other = tmp_path / "notes.md"
    other.write_text(f"old key {FAKE['google_api_key']}\nopenai {FAKE['openai_key']}\nnothing here\n")
    hits = secret_scan.scan([cassette, other])
    names = sorted(name for _, _, name in hits)
    assert names == ["bearer_literal", "google_api_key", "google_api_key_v2", "openai_key"], hits
    assert all(len(h) == 3 and not any(v in str(h) for v in FAKE.values()) for h in hits)


def test_the_repository_and_recorded_llm_data_hold_no_key():
    hits = secret_scan.scan(secret_scan.files())
    assert not hits, f"key-shaped strings found: {hits}"
