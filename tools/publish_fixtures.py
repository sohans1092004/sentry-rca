"""Package fixture datasets as deterministic tarballs, record their hashes in fixtures/index.json, and
upload them as assets of one GitHub Release per fixture version.

    uv run python tools/publish_fixtures.py [--version=v2] [--no-upload]

Deterministic: entries sorted, mtime/uid/gid zeroed, gzip header without a timestamp. Re-packaging
an unchanged dataset gives the same bytes, so the sha256 in index.json identifies the content.
"""

import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, LABELS = ROOT / "data" / "fixtures", ROOT / "fixtures"
OUT = ROOT / "data" / "release"
VERSION = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--version=")), "v2")  # v1: Phase 1 labels
TAG = f"fixtures-{VERSION}"
REPO = "sohans1092004/sentry-rca"


def package(fixture_id: str) -> Path:
    src = DATA / fixture_id / VERSION
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in sorted(src.iterdir()):
            info = tarfile.TarInfo(f"{fixture_id}/{VERSION}/{f.name}")
            data = f.read_bytes()
            info.size, info.mtime, info.mode, info.uid, info.gid = len(data), 0, 0o644, 0, 0
            tar.addfile(info, io.BytesIO(data))
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{fixture_id}-{VERSION}.tar.gz"
    with out.open("wb") as fh, gzip.GzipFile(filename="", fileobj=fh, mode="wb", mtime=0) as gz:
        gz.write(buf.getvalue())
    return out


def main() -> None:
    assets = []
    for d in sorted(p for p in LABELS.iterdir() if (p / VERSION / "label.json").exists()):
        tarball = package(d.name)
        sha = hashlib.sha256(tarball.read_bytes()).hexdigest()
        manifest = json.loads((DATA / d.name / VERSION / "manifest.json").read_text())
        assets.append({
            "fixture_id": d.name, "version": VERSION, "asset": tarball.name, "sha256": sha,
            "bytes": tarball.stat().st_size, "rows": {t: m["rows"] for t, m in manifest["tables"].items()},
        })  # fmt: skip
        print(f"{tarball.name}  {tarball.stat().st_size:>10,} B  sha256 {sha}")
    index = {"release": TAG, "url": f"https://github.com/{REPO}/releases/download/{TAG}/", "fixtures": assets}
    (LABELS / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    if "--no-upload" in sys.argv:
        return
    exists = subprocess.run(["gh", "release", "view", TAG, "-R", REPO], capture_output=True).returncode == 0
    if not exists:
        subprocess.run(["gh", "release", "create", TAG, "-R", REPO, "--title", f"Fixture datasets {VERSION}",
                        "--notes", f"Fixture datasets {VERSION} (Parquet + label/injection/manifest; v3 = dev and test splits). "
                        "Hashes in fixtures/index.json; fetch with tools/fetch_fixtures.py."], check=True)  # fmt: skip
    subprocess.run(["gh", "release", "upload", TAG, "-R", REPO, "--clobber", *[str(OUT / a["asset"]) for a in assets]],
                   check=True)  # fmt: skip


if __name__ == "__main__":
    main()
