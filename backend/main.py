"""FastAPI backend — redaction, local LLM stream, signed audit log.

Run: python -m uvicorn main:app --app-dir backend --port 8001 --reload

Routes used by frontend/backend_client.js + verifier:
  POST /redact  POST /local-infer (SSE)  POST /sign-event
  GET /health   GET /audit-log          POST /verify-log   GET /audit-summary
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

import audit_log
import local_llm
from crypto import public_key_b64, verify_log
from redactor import get_redactor

MAX_BYTES = int(os.getenv("MAX_INPUT_BYTES", os.getenv("INPUT_LIMIT_BYTES", "10240")))
_FRONTEND = os.getenv("FRONTEND_PORT", os.getenv("NODE_PORT", "3000"))
_CORS_ORIGINS = [
    f"http://localhost:{_FRONTEND}",
    f"http://127.0.0.1:{_FRONTEND}",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[py] session={audit_log.session_id()} verify_key={public_key_b64()[:20]}...")
    try:
        await local_llm.prewarm()
        print("[py] ollama prewarm done")
    except Exception as exc:
        print(f"[py] ollama prewarm skipped: {exc}")
    get_redactor()
    yield


app = FastAPI(title="TrustYourself Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RedactRequest(BaseModel):
    text: str


class InferRequest(BaseModel):
    prompt: str


class SignRequest(BaseModel):
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class VerifyRequest(BaseModel):
    envelopes: list[dict]
    expected_root: str


@app.get("/health")
async def health():
    ollama = await local_llm.health()
    return {
        "status": "ok",
        "service": "backend",
        "version": "0.1.0",
        "session_id": audit_log.session_id(),
        "ollama": ollama,
        "max_input_bytes": MAX_BYTES,
    }


@app.post("/redact")
async def redact_endpoint(req: RedactRequest):
    """Return tokenized text + events only (no side-effect audit row — same as early stub)."""
    if len(req.text.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Input exceeds {MAX_BYTES} bytes")

    redactor = get_redactor()
    redacted_text, events = redactor.redact(req.text)

    out_events = []
    for e in events:
        pub = e.to_public()
        pub["replacement"] = pub["placeholder"]
        out_events.append(pub)

    return {"redacted_text": redacted_text, "events": out_events}


@app.post("/local-infer")
async def local_infer(req: InferRequest):
    if len(req.prompt.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Prompt too large")

    async def gen():
        await audit_log.append(
            "local_infer_start",
            {"prompt_length": len(req.prompt), "model": local_llm.OLLAMA_MODEL},
        )

        async for ev in local_llm.generate_stream(req.prompt):
            if ev["type"] == "token":
                yield f"data: {json.dumps({'token': ev['text']})}\n\n"
            elif ev["type"] == "done":
                yield f"data: {json.dumps({'done': True, 'elapsed_ms': ev.get('elapsed_ms', 0)})}\n\n"
            elif ev["type"] == "error":
                yield f"data: {json.dumps({'error': ev['error']})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/sign-event")
async def sign_event_endpoint(req: SignRequest):
    envelope = await audit_log.append(req.event_type, req.payload)
    root = await audit_log.merkle_root_for_session()
    return {"envelope": envelope, "merkle_root": root}


@app.get("/audit-log")
async def get_audit_log():
    events = await audit_log.read_session()
    return {
        "session_id": audit_log.session_id(),
        "verify_key": public_key_b64(),
        "events": events,
        "merkle_root": await audit_log.merkle_root_for_session(),
    }


@app.get("/audit-summary")
async def audit_summary():
    return await audit_log.summary()


@app.post("/verify-log")
async def verify_endpoint(req: VerifyRequest):
    return verify_log(req.envelopes, req.expected_root)