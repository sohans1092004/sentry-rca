"""Download fixture datasets listed in fixtures/index.json, verify each tarball's sha256, extract.

Already-extracted fixtures are skipped (CI restores them from its cache). A hash mismatch is an error:
the dataset is refused, never used.
"""

import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "fixtures"
INDEX = ROOT / "fixtures" / "index.json"


class HashMismatch(Exception):
    pass


def fetch(index_path: Path = INDEX, data: Path = DATA) -> list[Path]:
    index = json.loads(index_path.read_text())
    out = []
    for a in index["fixtures"]:
        target = data / a["fixture_id"] / a["version"]
        if not (target / "manifest.json").exists():
            with urllib.request.urlopen(index["url"] + a["asset"], timeout=120) as r:
                blob = r.read()
            sha = hashlib.sha256(blob).hexdigest()
            if sha != a["sha256"]:
                raise HashMismatch(f"{a['asset']}: sha256 {sha} != index {a['sha256']}")
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
                tar.extractall(data, filter="data")
            print(f"{a['asset']}: {len(blob):,} B, sha256 verified", flush=True)
        out.append(target)
    return out
