"""Append-only audit log of signed envelopes.

Every redaction event, route decision, and model call lands here as a
signed envelope. Persisted to `audit-log.jsonl` at repo root (one JSON
envelope per line) so the demo survives a process restart and the
verifier page can reload prior sessions.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from crypto import sign, merkle_root, public_key_b64

_LOG_PATH = Path(__file__).resolve().parent.parent / "audit-log.jsonl"
_lock = asyncio.Lock()
_session_id = uuid.uuid4().hex[:12]


def session_id() -> str:
    return _session_id


def _hash_event_payload(event_type: str, data: dict) -> dict:
    return {
        "session_id": _session_id,
        "event_type": event_type,
        "ts_ms": int(time.time() * 1000),
        "data": data,
    }


async def append(event_type: str, data: dict[str, Any]) -> dict:
    """Sign an event payload and append the envelope to the log."""
    payload = _hash_event_payload(event_type, data)
    envelope = sign(payload)
    async with _lock:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(envelope) + "\n")
    return envelope


async def read_all() -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    async with _lock:
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


async def read_session(session: str | None = None) -> list[dict]:
    """Filter the on-disk log to a single session (default: current)."""
    target = session or _session_id
    return [e for e in await read_all() if e.get("payload", {}).get("session_id") == target]


async def merkle_root_for_session(session: str | None = None) -> str:
    return merkle_root(await read_session(session))


async def summary() -> dict:
    """Snapshot used by the UI receipt panel and verifier page."""
    events = await read_session()
    return {
        "session_id": _session_id,
        "event_count": len(events),
        "merkle_root": merkle_root(events),
        "verify_key": public_key_b64(),
    }
