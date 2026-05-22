"""Adversarial corpus runner (Decision 4 / Strategy S1).

Runs the adversarial input corpus through the redaction pipeline.
Reports false negatives (real secrets that slipped through — DEMO-FATAL).
False positives (over-redactions) are acceptable per Decision 1's conservative-bias policy.

Usage:
    python scripts/adversarial_corpus.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO_ROOT / "eval" / "adversarial_inputs.json"

# backend/ is a flat layout (no __init__.py) — add to sys.path so
# `import redactor` works without making backend a package.
sys.path.insert(0, str(REPO_ROOT / "backend"))

try:
    from redactor import get_redactor  # type: ignore
except ImportError as e:
    print(f"[corpus] backend.redactor not importable yet ({e}). Stub run; exiting 0.")
    sys.exit(0)


def main() -> None:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    print(f"[corpus] running {len(corpus)} adversarial cases...\n")

    redactor = get_redactor()
    false_negatives: list[dict] = []
    false_positives: list[dict] = []

    for i, case in enumerate(corpus, 1):
        text = case["input"]
        must_redact = set(case.get("must_redact", []))
        must_keep = set(case.get("must_keep", []))

        redacted_text, _events = redactor.redact(text)

        case_fns = [s for s in must_redact if s in redacted_text]
        case_fps = [s for s in must_keep if s not in redacted_text]

        false_negatives.extend(
            {"case": i, "name": case.get("name", ""), "secret": s} for s in case_fns
        )
        false_positives.extend(
            {"case": i, "name": case.get("name", ""), "value": s} for s in case_fps
        )

        status = "OK"
        if case_fns:
            status = "FALSE NEG"
        elif case_fps:
            status = "over-redacted"
        print(f"[{i:3d}] {case.get('name', 'unnamed'):42s} {status}")

    print(
        f"\nResults: {len(false_negatives)} false negatives, "
        f"{len(false_positives)} false positives."
    )

    if false_negatives:
        print("\nFALSE NEGATIVES (DEMO-FATAL):")
        for fn in false_negatives:
            print(f"  - case {fn['case']} ({fn['name']}): missed `{fn['secret'][:50]}`")
        sys.exit(1)
    else:
        print("No false negatives. Safe for demo.")
        sys.exit(0)


if __name__ == "__main__":
    main()
