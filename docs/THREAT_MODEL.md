# Threat Model

> Pitch deck slide. Locked during CEO review (Decision 4).
> Source of truth: `memory/tee-orchestrator-design.md`.

## Defended against

| Threat | How |
|--------|-----|
| Cloud LLM training pipeline ingesting sensitive data | Redactor tokenizes before egress; cloud-audit pane proves only tokens crossed |
| Provider data retention violating contract | Signed audit log gives customer ground truth — independently verifiable |
| Network MITM | TLS at transport layer + signed receipts prevent silent tampering |
| Insider threat at provider | Data is tokenized before leaving the customer's perimeter (TEE in v2) |
| Tampering with the audit log | Merkle log; any modification breaks the root verification |
| Demo-time adversarial input | Conservative-bias redactor (Decision 1) + adversarial corpus pre-flight (Decision 4 / S1) |

## Acknowledged limitations (honest about what we don't cover)

| Threat | Why we don't cover it (today) |
|--------|-------------------------------|
| TEE compromise | v2 only. Mitigated by hardware-vendor attestation chain (AWS Nitro / NVIDIA H100) |
| Side-channel attacks on TEEs | Academic risk; mitigations are vendor-level (microcode updates, mitigations like Intel TDX) |
| Prompt injection of local model | Output sandboxed to user-facing pane only; cloud-bound payload is constructed from tokenized input, not local model output |
| Cloud model "guessing" secret format | Cloud model never has the actual secret; it can only generate plausible-looking text. Reassembler rehydrates with real values inside the TEE in v2 |
| User endpoint compromise | Orthogonal to this product. If your laptop is owned, this product can't help you |
| Reassembler bug leaking to cloud | Mitigated by Decision 5 try/catch fallback (raw side-by-side display) + adversarial corpus testing |

## Trust boundaries

```
                 ┌────────────────────────────────────────────────┐
                 │  Trusted (inside TEE in v2)                    │
                 │                                                │
                 │  • Redactor (sees raw input)                   │
                 │  • Phi-3 local model (sees raw input)          │
                 │  • Signing key (ed25519)                       │
                 │  • Reassembler (sees both outputs)             │
                 │                                                │
                 └─────────────┬──────────────────────────────────┘
                               │
                               ▼ (only tokenized data crosses)
                 ┌────────────────────────────────────────────────┐
                 │  Untrusted (outside TEE)                       │
                 │                                                │
                 │  • OpenAI (gpt-4o-mini)                        │
                 │  • Network                                     │
                 │  • User-facing UI                              │
                 │                                                │
                 └────────────────────────────────────────────────┘
```

## What "verifiable" means in practice

A customer's compliance team:

1. Audits the open-source orchestrator code (this repo)
2. Verifies the deployed Nitro Enclave's image hash matches the audited build (via attestation document)
3. Receives signed audit logs from production sessions
4. Verifies signatures + Merkle root using only the public key — no provider trust required

The provider can lie. The cryptography can't.
