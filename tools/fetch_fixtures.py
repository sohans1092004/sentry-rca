"""Download fixture datasets listed in fixtures/index.json, verify each tarball's sha256, extract.

    uv run python tools/fetch_fixtures.py

Already-extracted fixtures are skipped (CI restores them from its cache). A hash mismatch is an error:
the dataset is refused, never used.
"""

import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "fixtures"


def main() -> int:
    index = json.loads((ROOT / "fixtures" / "index.json").read_text())
    for a in index["fixtures"]:
        target = DATA / a["fixture_id"] / a["version"]
        if (target / "manifest.json").exists():
            continue
        with urllib.request.urlopen(index["url"] + a["asset"], timeout=120) as r:
            blob = r.read()
        sha = hashlib.sha256(blob).hexdigest()
        if sha != a["sha256"]:
            print(f"{a['asset']}: sha256 {sha} != index {a['sha256']}", file=sys.stderr)
            return 1
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            tar.extractall(DATA, filter="data")
        print(f"{a['asset']}: {len(blob):,} B, sha256 verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
