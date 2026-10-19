"""Embedding cassette (Amendment A17): vectors recorded from a local model, replayed everywhere else.

Each entry is keyed by sha256(model name + model digest + text), so a different or updated model is a
loud miss, never silently stale vectors. Vectors are stored as exact float32 bytes (base64), so a
replayed similarity is bit-identical to the recorded one. Replay is the default; `live` records misses
through Ollama.
"""

import base64
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import httpx

MODEL = "nomic-embed-text"
DIM = 768
OLLAMA = "http://localhost:11434"
DEFAULT = Path(__file__).resolve().parent.parent / "runbooks" / "embeddings.json"


class CassetteMiss(KeyError):
    pass


def _pack(v: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(v)}f", *v)).decode()


def _unpack(s: str) -> list[float]:
    raw = base64.b64decode(s)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def ollama_digest(model: str = MODEL) -> str:
    tags = httpx.get(f"{OLLAMA}/api/tags", timeout=10).json()["models"]
    for m in tags:
        if m["name"].split(":")[0] == model:
            return str(m["digest"])
    raise RuntimeError(f"{model} is not pulled in Ollama (ollama pull {model})")


def ollama_embed(text: str, model: str = MODEL) -> list[float]:
    r = httpx.post(f"{OLLAMA}/api/embed", json={"model": model, "input": text}, timeout=120)
    r.raise_for_status()
    vec = [float(x) for x in r.json()["embeddings"][0]]
    if len(vec) != DIM:
        raise RuntimeError(f"{model} returned {len(vec)} dimensions, schema expects {DIM}")
    return list(struct.unpack(f"<{DIM}f", struct.pack(f"<{DIM}f", *vec)))  # rounded to float32, as stored


class Cassette:
    def __init__(self, path: Path = DEFAULT, live: bool = False):
        self.path, self.live = path, live
        data: dict[str, Any] = (
            json.loads(path.read_text()) if path.exists() else {"model": MODEL, "digest": "", "entries": {}}
        )
        self.model: str = data["model"]
        self.digest: str = data["digest"]
        self.entries: dict[str, dict[str, str]] = data["entries"]
        if live:
            self.digest = ollama_digest(self.model)

    def key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\n{self.digest}\n{text}".encode()).hexdigest()

    def embed(self, text: str) -> list[float]:
        k = self.key(text)
        if k in self.entries:
            return _unpack(self.entries[k]["vector"])
        if not self.live:
            raise CassetteMiss(f"no recorded embedding for {text[:60]!r} ({self.model}@{self.digest[:12]}); "
                               "re-record locally with `rca runbooks embed --live`")  # fmt: skip
        vec = ollama_embed(text, self.model)
        self.entries[k] = {"text": text, "vector": _pack(vec)}
        return vec

    def save(self) -> None:
        body = {"model": self.model, "digest": self.digest, "entries": dict(sorted(self.entries.items()))}
        self.path.write_text(json.dumps(body, indent=1) + "\n")

    def drift(self, tolerance: float = 1e-6) -> list[tuple[str, float]]:
        """Re-embed every recorded text with the live model; (text, max abs difference) beyond tolerance."""
        if ollama_digest(self.model) != self.digest:
            return [("<model digest changed>", float("inf"))]
        out = []
        for e in self.entries.values():
            live = ollama_embed(e["text"], self.model)
            diff = max(abs(a - b) for a, b in zip(live, _unpack(e["vector"]), strict=True))
            if diff > tolerance:
                out.append((e["text"][:60], diff))
        return out
