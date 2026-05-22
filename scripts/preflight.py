"""Pre-demo smoke test (Decision 6).

Run 10 minutes before going on stage. Verifies the entire pipeline works end-to-end.
Cross-platform (Python only, no bash).

Exit codes:
  0  - All systems go
  1  - Critical failure (cannot demo)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def check(name: str, fn) -> tuple[bool, str]:
    print(f"[ ] {name:32s} ", end="", flush=True)
    try:
        ok, msg = fn()
        prefix = "OK  " if ok else "FAIL"
        print(f"{prefix} - {msg}")
        return ok, msg
    except Exception as e:
        print(f"FAIL - {e!r}")
        return False, str(e)


def check_ollama():
    import httpx

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    r = httpx.get(f"{host}/api/tags", timeout=2.0)
    r.raise_for_status()
    models = [m["name"] for m in r.json().get("models", [])]
    target = os.environ.get("OLLAMA_MODEL", "phi3:mini")
    target_base = target.split(":")[0]
    if any(m == target or m.startswith(target_base) for m in models):
        return True, f"{target} pulled ({len(models)} models)"
    return False, f"{target} not pulled. Run: ollama pull {target}"


def check_openai():
    import httpx

    key = os.environ.get("OPENAI_API_KEY", "")
    if not key or key.startswith("sk-replace") or len(key) < 20:
        return False, "OPENAI_API_KEY not set or placeholder"
    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
        timeout=10.0,
    )
    if r.status_code == 200:
        return True, f"key valid ({r.elapsed.total_seconds():.2f}s)"
    return False, f"OpenAI returned {r.status_code}: {r.text[:120]}"


def check_backend():
    import httpx

    port = os.environ.get("PY_PORT", os.environ.get("BACKEND_PORT", "8001"))
    try:
        r = httpx.get(f"http://localhost:{port}/health", timeout=1.0)
        if r.status_code == 200:
            data = r.json()
            ollama_ok = data.get("ollama", {}).get("ok", False)
            ollama_pulled = data.get("ollama", {}).get("model_pulled", False)
            extras = []
            if not ollama_ok:
                extras.append("ollama down")
            elif not ollama_pulled:
                extras.append("model not pulled")
            suffix = f" ({', '.join(extras)})" if extras else ""
            return True, f"healthy ({r.elapsed.total_seconds()*1000:.0f}ms){suffix}"
        return False, f"returned {r.status_code}"
    except httpx.ConnectError:
        return False, f"not running on :{port} — start with `npm run dev`"


def check_examples():
    p = REPO_ROOT / "eval" / "pre_loaded_examples.json"
    if not p.exists():
        return False, "eval/pre_loaded_examples.json missing"
    examples = json.loads(p.read_text(encoding="utf-8"))
    if len(examples) < 3:
        return False, f"only {len(examples)} examples (need 3)"
    return True, f"{len(examples)} demo examples"


def check_signing():
    from nacl.signing import SigningKey

    sk = SigningKey.generate()
    signed = sk.sign(b"smoke test")
    sk.verify_key.verify(signed.message, signed.signature)
    return True, "ed25519 sign+verify works"


CHECKS = [
    ("Ollama responsive", check_ollama),
    ("OpenAI API key", check_openai),
    ("Backend service", check_backend),
    ("Demo examples loaded", check_examples),
    ("ed25519 signing", check_signing),
]


def main():
    print(f"[preflight] running {len(CHECKS)} smoke tests...\n")
    results = [check(name, fn) for name, fn in CHECKS]
    print()
    failures = sum(1 for ok, _ in results if not ok)
    if failures == 0:
        print("[preflight] ALL CHECKS PASSED. Demo go.")
        sys.exit(0)
    else:
        print(f"[preflight] {failures}/{len(CHECKS)} failed. Fix before demo.")
        sys.exit(1)


if __name__ == "__main__":
    main()
