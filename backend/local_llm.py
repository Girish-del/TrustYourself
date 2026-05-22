"""Ollama client — local inference for Beat 2 (Decision 2: M2 mechanism).

The local model receives the **full original prompt** (with raw secrets).
Per Decision 3 (T1 architecture) this stays inside the TEE in production;
in the v1 prototype it stays inside the Python service.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import AsyncIterator

import httpx

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3:mini")

_HEALTH_TIMEOUT_S = 0.5
_GENERATE_TIMEOUT_S = 60.0


class OllamaUnavailable(RuntimeError):
    """Raised when Ollama doesn't respond within the health budget."""


async def health() -> dict:
    """Cheap liveness probe used by the UI's health dot + Decision 5 fallback."""
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_S) as client:
            r = await client.get(f"{OLLAMA_HOST}/api/tags")
            ok = r.status_code == 200
            tags = r.json().get("models", []) if ok else []
            has_model = any(m.get("name", "").startswith(OLLAMA_MODEL) for m in tags)
            return {
                "ok": ok,
                "model": OLLAMA_MODEL,
                "model_pulled": has_model,
                "host": OLLAMA_HOST,
            }
    except Exception as exc:
        return {"ok": False, "model": OLLAMA_MODEL, "host": OLLAMA_HOST, "error": str(exc)}


async def prewarm() -> None:
    """Decision 5: pre-warm Ollama at startup with a tiny dummy query."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": "hi", "stream": False, "options": {"num_predict": 4}},
            )
    except Exception as exc:
        print(f"[local_llm] prewarm skipped: {exc}")


async def generate_stream(prompt: str, *, system: str | None = None) -> AsyncIterator[dict]:
    """Stream tokens from Ollama. Yields dicts of shape:
        {"type": "token", "text": "..."}      — incremental token
        {"type": "done", "elapsed_ms": int}   — final marker
        {"type": "error", "error": str}       — on failure
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {"temperature": 0.2, "num_predict": 256},
    }
    if system:
        payload["system"] = system

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_GENERATE_TIMEOUT_S) as client:
            async with client.stream("POST", f"{OLLAMA_HOST}/api/generate", json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    yield {"type": "error", "error": f"ollama HTTP {resp.status_code}: {body[:200]}"}
                    return
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        import json as _json
                        chunk = _json.loads(line)
                    except Exception:
                        continue
                    text = chunk.get("response", "")
                    if text:
                        yield {"type": "token", "text": text}
                    if chunk.get("done"):
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        yield {"type": "done", "elapsed_ms": elapsed_ms}
                        return
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        yield {"type": "error", "error": f"ollama unreachable: {exc}"}
    except Exception as exc:  # pragma: no cover - defensive
        yield {"type": "error", "error": f"ollama stream failed: {exc}"}


async def generate_full(prompt: str, *, system: str | None = None) -> str:
    """Non-streaming convenience used by the reassembler in the Python path."""
    out: list[str] = []
    async for ev in generate_stream(prompt, system=system):
        if ev["type"] == "token":
            out.append(ev["text"])
        elif ev["type"] == "error":
            raise OllamaUnavailable(ev["error"])
    return "".join(out)


# Allow direct CLI sanity check: `python local_llm.py "what is 2+2"`
if __name__ == "__main__":  # pragma: no cover
    import sys

    async def _main() -> None:
        prompt = " ".join(sys.argv[1:]) or "what is 2+2"
        async for ev in generate_stream(prompt):
            if ev["type"] == "token":
                print(ev["text"], end="", flush=True)
            elif ev["type"] == "done":
                print(f"\n[done in {ev['elapsed_ms']}ms]")
            elif ev["type"] == "error":
                print(f"\n[error] {ev['error']}")

    asyncio.run(_main())
