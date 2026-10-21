"""LLM providers, recording and replay (SPEC §7.4, ADR-000, Amendment A35).

Provider interface: `complete(messages, tools, temperature=0) -> Response`. Ollama on the host is the
default; one OpenAI-compatible HTTP provider (any free-tier endpoint) exists, disabled unless its key is
set. Neither is required to run the tests or CI: CI replays.

Every exchange is recorded: in `llm_exchanges` (the investigation's audit, written by the agent loop) and
in a per-fixture cassette. The cassette key is sha256(model + model digest + canonical request +
run_index): a different model, a different digest, a different prompt or another run is a miss, and a
miss in replay fails loudly instead of calling a live model or returning another request's response.
The canonical request replaces each data-block boundary (random per tool call, A35) with a placeholder.
"""

import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
NUM_CTX = 8192  # context window asked of Ollama; part of the recorded request
RETRIES = 3  # §15 row 7: retry with backoff up to a cap, then the investigation degrades
BACKOFF_S = 1.0
BOUNDARY = re.compile(r"DATA-[0-9a-f]{16}")


class Unavailable(Exception):
    """The model could not be reached or kept failing; the investigation degrades to the baseline."""


class ReplayMiss(Exception):
    """Replay mode found no recorded response for this exact request. Never answered by a live model."""


@dataclass
class Response:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # [{"name": str, "arguments": dict}]
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


class Provider(Protocol):
    name: str
    model: str
    digest: str

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], temperature: float = 0.0
    ) -> Response: ...


def canonical_request(model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                      temperature: float) -> dict[str, Any]:  # fmt: skip
    return {"model": model, "messages": messages, "tools": tools, "temperature": temperature, "num_ctx": NUM_CTX}


def request_hash(model: str, digest: str, request: dict[str, Any], run_index: int) -> str:
    body = BOUNDARY.sub("DATA-<boundary>", json.dumps(request, sort_keys=True, separators=(",", ":")))
    return hashlib.sha256(f"{model}\n{digest}\n{body}\n{run_index}".encode()).hexdigest()


def _post(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    """POST with retries and exponential backoff on connection errors, timeouts, 429 and 5xx."""
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}: {r.text[:200]}", request=r.request, response=r)
            r.raise_for_status()
            return dict(r.json())
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last = e
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500 and e.response.status_code != 429:
                break  # a 4xx other than 429 will not get better
            if attempt + 1 < RETRIES:
                time.sleep(BACKOFF_S * 2**attempt)
    raise Unavailable(f"{url}: {type(last).__name__}: {last}")


class Ollama:
    name = "ollama"

    def __init__(self, model: str, timeout_s: float = 300.0):
        self.model, self.timeout_s = model, timeout_s
        self.digest = ollama_digest(model)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                 temperature: float = 0.0) -> Response:  # fmt: skip
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False,
                                "options": {"temperature": temperature, "seed": 0, "num_ctx": NUM_CTX}}  # fmt: skip
        if tools:
            body["tools"] = tools
        t0 = time.monotonic()
        out = _post(f"{OLLAMA}/api/chat", body, {}, self.timeout_s)
        msg = out.get("message", {})
        calls = [{"name": c["function"]["name"], "arguments": c["function"].get("arguments") or {}}
                 for c in msg.get("tool_calls") or []]  # fmt: skip
        return Response(str(msg.get("content", "")), calls, int(out.get("prompt_eval_count", 0)),
                        int(out.get("eval_count", 0)), int((time.monotonic() - t0) * 1000))  # fmt: skip


def ollama_digest(model: str) -> str:
    try:
        tags = httpx.get(f"{OLLAMA}/api/tags", timeout=10).json()["models"]
    except (httpx.TransportError, ValueError) as e:
        raise Unavailable(f"Ollama at {OLLAMA}: {e}") from e
    for m in tags:
        if m["name"] == model or m["name"] == f"{model}:latest":
            return str(m["digest"])
    raise Unavailable(f"{model} is not pulled in Ollama (ollama pull {model})")


class OpenAICompatible:
    """An optional hosted model (any OpenAI-compatible chat endpoint with a free tier), enabled only when
    LLM_API_KEY is set. Used only for a clearly labelled DEV comparison, never by default."""

    name = "openai_compatible"

    def __init__(self, model: str, base_url: str | None = None, timeout_s: float = 120.0):
        key = os.environ.get("LLM_API_KEY")
        if not key:
            raise Unavailable("LLM_API_KEY is not set: the hosted provider is disabled")
        self.model, self.timeout_s = model, timeout_s
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", "")
        self.digest = f"hosted:{self.base_url}"  # a hosted model has no digest; its name and endpoint stand in
        self._headers = {"Authorization": f"Bearer {key}"}  # never logged or recorded

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                 temperature: float = 0.0) -> Response:  # fmt: skip
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": temperature}
        if tools:
            body["tools"] = tools
        t0 = time.monotonic()
        out = _post(f"{self.base_url}/chat/completions", body, self._headers, self.timeout_s)
        msg = out["choices"][0]["message"]
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_unparsed": c["function"].get("arguments")}
            calls.append({"name": c["function"]["name"], "arguments": args})
        usage = out.get("usage", {})
        return Response(str(msg.get("content") or ""), calls, int(usage.get("prompt_tokens", 0)),
                        int(usage.get("completion_tokens", 0)), int((time.monotonic() - t0) * 1000))  # fmt: skip


class Cassette:
    """Recorded responses for one fixture and one model: {key: {run_index, seq, response}}."""

    def __init__(self, path: Path, model: str, digest: str):
        self.path, self.model, self.digest = path, model, digest
        self.entries: dict[str, dict[str, Any]] = {}
        if path.exists():
            data = json.loads(path.read_text())
            if (data["model"], data["digest"]) != (model, digest):
                raise ReplayMiss(f"{path} was recorded with {data['model']}@{data['digest'][:12]}, "
                                 f"not {model}@{digest[:12]}")  # fmt: skip
            self.entries = data["entries"]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {"model": self.model, "digest": self.digest, "entries": dict(sorted(self.entries.items()))}
        self.path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")


def cassette_header(path: Path) -> tuple[str, str]:
    data = json.loads(path.read_text())
    return str(data["model"]), str(data["digest"])


Sink = Callable[[str, int, str, dict[str, Any], Response], None]  # (provider, seq, hash, request, response)


class Recorded:
    """Wraps a provider for one investigation run. mode "live": call the inner provider (no cassette);
    "record": call it and store each response under its key; "replay": answer only from the cassette,
    and raise ReplayMiss otherwise. Every exchange goes to `sink` (the agent's llm_exchanges writer)
    before the response is returned, so a crash right after a model call loses nothing."""

    def __init__(self, cassette: Cassette | None, run_index: int, mode: str, inner: Provider | None = None,
                 sink: Sink | None = None):  # fmt: skip
        if mode not in ("live", "record", "replay"):
            raise ValueError(mode)
        if mode != "replay" and inner is None:
            raise ValueError(f"{mode} mode needs a live provider")
        if mode != "live" and cassette is None:
            raise ValueError(f"{mode} mode needs a cassette")
        self.cassette, self.run_index, self.mode, self.inner, self.sink = cassette, run_index, mode, inner, sink
        self.name = inner.name if inner else "replay"
        src: Any = cassette if cassette is not None else inner
        self.model, self.digest = str(src.model), str(src.digest)
        self.seq = 0
        self.exchanges: list[tuple[str, dict[str, Any], Response]] = []

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                 temperature: float = 0.0) -> Response:  # fmt: skip
        request = canonical_request(self.model, messages, tools, temperature)
        key = request_hash(self.model, self.digest, request, self.run_index)
        self.seq += 1
        hit = self.cassette.entries.get(key) if self.cassette is not None and self.mode != "live" else None
        if hit is not None:
            resp = Response(**hit["response"])
        elif self.mode == "replay":
            where = self.cassette.path if self.cassette else "-"
            raise ReplayMiss(f"no recorded response for request {key[:12]} (run {self.run_index}, exchange "
                             f"{self.seq}, {self.model}@{self.digest[:12]}) in {where}")  # fmt: skip
        else:
            assert self.inner is not None
            resp = self.inner.complete(messages, tools, temperature)
            if self.cassette is not None:
                self.cassette.entries[key] = {"run_index": self.run_index, "seq": self.seq, "response": asdict(resp)}
        if self.sink is not None:
            self.sink(self.name, self.seq, key, request, resp)
        self.exchanges.append((key, request, resp))
        return resp
