# 90-Second Demo Script

> **Lock this BEFORE writing any code.** (Office-hours assignment from `memory/tee-orchestrator-design.md`)
> Time yourself reading aloud. If >100 seconds, cut.
> Status: **TEMPLATE — fill in your exact words below**

## Pre-demo setup (do BEFORE judges arrive)

- [ ] App running at http://localhost:3000
- [ ] Health dot is green
- [ ] Auth handler example pre-loaded but not submitted
- [ ] Audit panes collapsed (Decision 7)
- [ ] Cursor enlarged (Windows accessibility) for laptop demo (Decision 9)
- [ ] Backup video ready in second tab (H21 deliverable)

---

## TOTAL: 90 seconds

### Beat 1 — Live Redaction (30s)

**Hook (5s):** "When you paste code into ChatGPT, your API keys go to OpenAI's training pipeline. Watch what happens here instead."

**Action (5s):** Click "Auth handler" pre-load, then click "Run."

**Observation (15s):** [Pause for the gasp.] Animated sidebar: secret detected → tokenized; PII detected → tokenized; hostname detected → tokenized. Each entry shows the rule that fired.

**Bridge (5s):** "All of this happened in 200 milliseconds. None of it has touched the cloud yet."

### Beat 2 — Hybrid Routing (30s)

**Setup (5s):** "Now I send the request. Two streams launch in parallel."

**Stream demo (15s):** Cloud stream (left) streams structural reasoning from gpt-4o-mini. Local stream (right) streams secret-aware completion from Phi-3 — running on this laptop, never leaving. Reassembler stitches them; final output appears below.

**Audit reveal (10s):** [Click to expand "Verify cloud request bytes."] "This is exactly what gpt-4o-mini saw. Tokenized only. The actual API key never crossed the boundary."

### Beat 3 — Verifiable Receipt (20s)

**Setup (5s):** "Every redaction, every routing decision, every model call is signed."

**Verify (10s):** Click "Show signed audit log." JSON drops out. Show the Merkle root. "In production this signing key lives inside an AWS Nitro Enclave with hardware attestation. Today's demo uses a software key — the protocol and verifier are identical."

**Closer (5s):** "v1 prototype. v2 ships in 2 days on Nitro. Same code, hardware-rooted trust."

---

## Variations

### If a judge asks "can I paste my own code?"
> *"Absolutely. This is a 24-hour prototype — Presidio + gitleaks catch about 90% of patterns. The cloud-audit pane is your verifier. If you find something that slips through, that's a real bug we want to know about."*
(Decision 4 / S5 — turns attackers into collaborators.)

### If something breaks (graceful recovery)
- **Local stream hangs** → Auto-fallback banner appears; say *"local model temporarily unavailable, showing cloud path only."* Continue.
- **OpenAI rate-limited** → *"OpenAI rate-limited, retrying..."* If persists, switch to backup video.
- **Reassembler errors** → Side-by-side raw outputs appear automatically (Decision 5). Say *"reassembler is hardened to show both streams when merge fails."*
- **Anything weirder** → *"Let me show you with a known-good example."* Click pre-loaded auth handler.

### If demo dies completely
Play the 90-second backup video (recorded H20-21).

### If a judge asks about TEE specifically
> *"Today the orchestrator runs as a normal process. In production we package it as a Nitro Enclave image — the redactor, the local model, and the signing key all live inside hardware-attested memory. Cloud calls go out through a vsock proxy after tokenization. The customer's compliance team can verify the deployed enclave hash matches the audited code."*

### If a judge asks "what's the moat?"
> *"Three things in one tool: redaction with conservative bias, hybrid routing with reassembly, and cryptographic receipts that customers can audit. Skyflow does redaction. Anjuna does confidential computing. Nobody packages all three with a UX that makes the trust property visible to a non-engineer in 5 seconds."*
