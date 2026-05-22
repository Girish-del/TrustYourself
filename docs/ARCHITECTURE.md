# Architecture

## Hybrid Stack (Decision 8)

Two services running on one laptop, talking over localhost HTTP.

```
┌─────────────────────────────┐         ┌──────────────────────────────┐
│  Frontend (Node, :3000)     │         │  Backend (Python, :8001)     │
│                             │         │                              │
│  • Express                  │  HTTP   │  • FastAPI                   │
│  • UI (HTML/CSS/vanilla JS) │ ──────▶ │  • Presidio + gitleaks       │
│  • OpenAI SDK (gpt-4o-mini) │ ◀────── │  • Ollama client (Phi-3)     │
│  • Reassembler              │         │  • ed25519 + Merkle log      │
│  • Health-dot poller        │         │                              │
└─────────────────────────────┘         └──────────────────────────────┘
       │                                         │
       │ HTTPS                                   │ localhost
       ▼                                         ▼
   OpenAI API                                Ollama (:11434)
```

## TEE Wrap — T1 (Decision 3)

In v2 production, the entire backend runs inside a TEE (AWS Nitro Enclave or
NVIDIA H100 confidential mode). Cloud calls leave the enclave only after
tokenization via a controlled vsock proxy.

```
                       ┌─────────────────────────────────────┐
                       │         TEE / Nitro Enclave         │
                       │                                     │
   user input  ───────▶│  Redactor  ──▶  Phi-3 (local)       │
                       │     │                  │            │
                       │     ▼                  │            │
                       │  Tokenized prompt      │            │
                       │     │                  │            │
                       │     │             [secrets stay     │
                       │     │              inside TEE]      │
                       │     ▼                  │            │
                       │  vsock proxy           │            │
                       │     │                  │            │
                       └─────│──────────────────│────────────┘
                             ▼                  ▼
                          OpenAI           Reassembler
                         (cloud)         (inside TEE)
                                              │
                                              ▼
                                        Final output
                                        + signed receipt
                                        + Merkle root
```

**Inside the TEE:** redactor, Phi-3 local model, signing key, reassembler.
**Outside the TEE:** OpenAI (gets only tokenized prompts), the user's UI.
**Attestation:** enclave image hash signed by the hardware vendor (AWS Nitro / NVIDIA H100). Customer verifies the deployed code matches the audited code.

## Beat 2 Mechanism — M2 (Decision 2)

For each user prompt, both streams launch in parallel:

| Stream | Receives | Returns |
|--------|----------|---------|
| **Cloud (gpt-4o-mini)** | Tokenized prompt with `<SECRET_001>`, `<PII_001>`, etc. | Structural reasoning, placeholders preserved |
| **Local (Phi-3 in TEE)** | Original prompt with raw secrets | Secret-aware shadow answer |

The reassembler merges them: rehydrates cloud's placeholders with original values from the redaction events. Cloud has structure; local has secrets; neither alone has both.

## Trust Properties (what the demo proves)

| Property | Demonstrated by |
|----------|-----------------|
| Sensitive data never reaches OpenAI training | Cloud-audit pane shows exact bytes sent — only tokenized prompts |
| Trust is verifiable, not assumed | Beat 3 signed audit log + public verifier page |
| Both streams do real work | Beat 2 side-by-side latency counters; reassembler merges meaningfully |
| Production differs only in attestation | Same code paths in v1 (software keys) and v2 (TEE-rooted keys) |

## Data Flow Summary

1. User pastes input → frontend
2. Frontend `POST /api/chat` → `runChat()` in reassembler
3. Reassembler `POST /redact` → backend → returns `{redacted_text, events[]}`
4. Reassembler signs each redaction event via `POST /sign-event`
5. Reassembler launches in parallel:
   - `cloudStream(redacted_text)` → OpenAI
   - `localInferStream(prompt)` → backend `POST /local-infer` → Ollama → Phi-3
6. Both streams emit tokens via SSE to the frontend UI
7. Reassembler joins both responses, rehydrates cloud's output with original values
8. Reassembler signs `completion` event → backend appends to Merkle log
9. UI fetches `/audit-log` on demand → judge verifies signature chain

## Cross-Platform Notes (Decision 8)

- All scripts in `scripts/` are Python or Node — never bash
- Path handling: `pathlib.Path` (Python), `path.join` (Node)
- Process orchestration: `concurrently` package via `npm run dev`
- Tested on Windows 10/11; should work on macOS/Linux without changes
