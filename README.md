# TrustYourself

A hackathon prototype that redacts sensitive content, routes work between a **local** model (Ollama / Phi-3) and a **cloud** model (OpenAI), reassembles the answer, and appends **signed** events to an audit log.

For the full product vision and locked decisions, see [`memory/tee-orchestrator-design.md`](memory/tee-orchestrator-design.md).

## Project Preview

## Page Preview

![Page Preview](Project%20Preview/Page%20Preview.png)

## Live Redaction

![Live Redaction](Project%20Preview/Live%20redaction%20.png)

## Cloud Stream and Non Cloud Stream Data

![Cloud Stream and Non Cloud Stream Data](Project%20Preview/Cloud%20stream%20and%20non%20cloud%20stream%20data.png)

## Reassembled Answer and Signed Receipt

![Reassembled Answer and Signed Receipt](Project%20Preview/Reassembeled%20Answer%20and%20Signed%20receipt.png)

## Cloud Sent Data

![Cloud Sent Data and Final Query](Project%20Preview/Cloud%20sent%20data%20and%20final%20query.png)

## Final Query

![Final Query](Project%20Preview/Final%20query.png)

## Session Receipt

![Session Receipt](Project%20Preview/Session%20receipt.png)
---

## What runs where

| Piece | Tech | URL / port |
|-------|------|------------|
| **Frontend + orchestrator** | Node (Express), static HTML/CSS/JS | **http://localhost:3000** |
| **Backend** | Python (FastAPI): redactor, Ollama proxy, signing, audit log | **http://localhost:8001** |
| **Local LLM** | Ollama (must be installed separately) | **http://localhost:11434** (default) |

`npm run dev` starts **both** the backend and frontend from the repo root using `concurrently`.

---

## Prerequisites (install once)

| Requirement | Notes |
|-------------|--------|
| **Python 3.10+** | Use `python --version`. |
| **Node.js 18+** | Use `node --version`. Native `fetch` is required (bundled in Node 18+). |
| **[Ollama](https://ollama.com)** | Install and keep it **running** so `http://localhost:11434` responds. |
| **OpenAI API key** | Used only by the Node layer for the cloud stream (`gpt-4o-mini` by default). |

---

## First-time setup (step by step)

Do these from the **repository root** (the folder that contains `package.json`).

### 1. Install Ollama and pull the local model

```powershell
ollama pull phi3:mini
```

Quick check:

```powershell
ollama run phi3:mini "what is 2+2"
```

If this hangs or errors, fix Ollama before continuing.

### 2. Create a Python virtual environment and install backend dependencies

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python -m spacy download en_core_web_sm
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m spacy download en_core_web_sm
```

Presidio’s analyzer expects an English spaCy model; `en_core_web_sm` is the smallest standard choice. If redactor startup warns about Presidio, confirm this download finished without errors.

Deactivate the venv when finished (`deactivate`) if you like—the next section assumes you will activate it again before `npm run dev`.

### 3. Install Node dependencies (repo root)

```powershell
npm install
```

This installs root-level packages (`concurrently`, `express`, `openai`, etc.) used by `frontend/server.js`. There is **no** separate `npm install` inside `frontend/`.

### 4. Configure environment variables

```powershell
copy .env.example .env
```

Edit `.env` and set at minimum:

- **`OPENAI_API_KEY`** — your real key (not `sk-replace-me`).

Optional overrides (defaults match `.env.example`):

- **`OPENAI_MODEL`** — default `gpt-4o-mini`.
- **`OLLAMA_HOST`** — default `http://localhost:11434`.
- **`OLLAMA_MODEL`** — default `phi3:mini` (must match a model you pulled).
- **`PY_PORT`** — backend port (default `8001`).
- **`NODE_PORT`** — frontend port (default `3000`).
- **`MAX_INPUT_BYTES`** — demo input cap (default `10240`).

Both services load **`.env` from the repo root** (`frontend/server.js` resolves it explicitly).

---

## Run the application

### 1. Start Ollama

Ensure the Ollama app/daemon is running (Windows: system tray; CLI: `ollama serve` if you use it headless).

### 2. Activate the Python virtual environment

**Windows:**

```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

### 3. Start backend + frontend together

From the **repo root**, with the venv **activated**:

```powershell
npm run dev
```

You should see two labeled streams:

- **`[py]`** — Uvicorn serving FastAPI from `backend/` on port **8001** (with `--reload`).
- **`[node]`** — Express from `frontend/server.js` on port **3000**.

Wait until both show listening / startup lines with **no** Python tracebacks (missing spaCy model is a common first-run failure).

### 4. Open the UI

In a browser:

**http://localhost:3000**

The header shows health dots for Node, Python, and Ollama. Green means the corresponding check passed.

**Verifier page (Beat 3):** http://localhost:3000/verifier.html

---

## Smoke test before a demo

The preflight script expects the **backend** to answer `GET http://localhost:PY_PORT/health`.

**Terminal 1 — keep running:**

```powershell
npm run dev
```

**Terminal 2 — after both processes are up:**

```powershell
.\.venv\Scripts\Activate.ps1
npm run preflight
```

Equivalent:

```powershell
python scripts/preflight.py
```

It checks, in order: Ollama tags/API, OpenAI key with a 1-token chat completion, **`GET /health` on the Python service**, presence of demo examples under `eval/`, and ed25519 sign/verify.

**Exit code `0`** means proceed; **`1`** means fix the printed failures before relying on a live demo.

---

## Optional: adversarial redaction corpus

Runs JSON inputs through the backend redactor only (no HTTP):

```powershell
.\.venv\Scripts\Activate.ps1
npm run adversarial
```

Same as `python scripts/adversarial_corpus.py`. Requires `eval/adversarial_inputs.json`.

---

## Troubleshooting

| Symptom | What to check |
|--------|----------------|
| **`npm run dev` fails with “python not found” or wrong packages** | Activate `.venv` **before** `npm run dev`. The `dev:backend` script uses `python -m uvicorn`; that must resolve to the venv interpreter. |
| **`POST /redact` → 500, log mentions Presidio / spaCy / `SystemExit`** | Presidio needs an English spaCy model **already installed** (the app no longer runs pip downloads during requests). **Stop** `npm run dev`, then run `python -m spacy download en_core_web_sm` (or the model in `PRESIDIO_SPACY_MODEL`). Confirm: `python -c "import spacy; spacy.load('en_core_web_sm')"`. Start `npm run dev` again. |
| **WatchFiles / reload fired while installing packages** | Do **not** run `pip install …` into `.venv` while Uvicorn `--reload` is running—restart dev after installs. The dev script excludes `.venv` from reload, but staying consistent avoids odd states. |
| **Backend exits on import / Presidio errors** | Run `pip install -r backend/requirements.txt` inside the venv. Run `python -m spacy download en_core_web_sm`. |
| **Port 8001 or 3000 already in use** | Stop the other process or change `PY_PORT` / `NODE_PORT` in `.env` (use the **same** `.env` for both services). |
| **Frontend loads but health dots are red for Python** | Confirm `http://localhost:8001/health` in the browser. Fix backend startup errors in the `[py]` terminal. |
| **Ollama health fails** | Confirm `ollama list` shows `phi3:mini`. Run `ollama pull phi3:mini` again. Start Ollama. |
| **Cloud stream errors / “OPENAI”** | Valid `OPENAI_API_KEY` in root `.env`. Billing/quota on the OpenAI account. |
| **`preflight` fails on “Backend service”** | Backend not listening yet—wait for Uvicorn “Application startup complete”, or run `npm run dev` in another terminal. |

---

## Project layout (actual repo)

```
backend/           FastAPI app (main.py), redactor, local_llm, crypto, audit_log; requirements.txt
frontend/          Express server.js, cloud_llm.js, reassembler.js, public/ (HTML, CSS, JS)
scripts/           preflight.py, adversarial_corpus.py
eval/              Demo / adversarial JSON inputs
docs/              ARCHITECTURE.md, DEMO_SCRIPT.md, THREAT_MODEL.md
memory/            tee-orchestrator-design.md (locked design source)
```

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [`memory/tee-orchestrator-design.md`](memory/tee-orchestrator-design.md) | Locked plan, decisions, scope |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | T1 TEE wrap + hybrid stack |
| [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | 90-second demo script |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | Threat model |

---

## Status

Hackathon prototype. Production story (real TEE attestation, IDE integration, multi-provider routing) is deferred per the design doc.
