"""Conservative-bias redactor (Decision 1).

Stacks Presidio (PII) + a gitleaks-style regex pack (secrets) +
entropy/literal/PEM/hostname catchers. Bias: prefer false positives
over false negatives. Over-redaction is acceptable; under-redaction
is demo-fatal.

Returns the redacted text alongside a list of `RedactionEvent`s
suitable for the animated sidebar and the signed audit log.
"""

from __future__ import annotations

import math
import os
import re
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Iterable

try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    _PRESIDIO_AVAILABLE = True
except Exception:  # pragma: no cover - presidio optional at import time
    AnalyzerEngine = None  # type: ignore[assignment]
    NlpEngineProvider = None  # type: ignore[assignment,misc]
    _PRESIDIO_AVAILABLE = False

# Presidio defaults to a large model and may call spaCy’s downloader on first use.
# That path can invoke sys.exit(1) on failure and crash Uvicorn. We always:
#   1) Verify the model loads with spacy.load first.
#   2) Wire AnalyzerEngine with NlpEngineProvider (no implicit default pipeline).
# Override with env PRESIDIO_SPACY_MODEL if needed.
_DEFAULT_SPACY_MODEL = "en_core_web_sm"


def _create_presidio_analyzer() -> Any:
    """Build AnalyzerEngine after confirming the spaCy model is already installed.

    Never triggers spaCy’s pip-based downloader during an HTTP request.
    """
    if not _PRESIDIO_AVAILABLE or AnalyzerEngine is None or NlpEngineProvider is None:
        raise RuntimeError("presidio_analyzer is not installed")

    model_name = os.getenv("PRESIDIO_SPACY_MODEL", _DEFAULT_SPACY_MODEL)

    import spacy

    try:
        spacy.load(model_name)
    except OSError as exc:
        raise RuntimeError(
            f"spaCy model {model_name!r} is not installed or is broken. "
            "Stop `npm run dev`, then run:\n"
            f"  python -m spacy download {model_name}\n"
            "Then verify: python -c \"import spacy; spacy.load('" + model_name + "')\""
        ) from exc

    configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": model_name}],
    }
    provider = NlpEngineProvider(nlp_configuration=configuration)
    nlp_engine = provider.create_engine()
    return AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])


# ---------------------------------------------------------------------------
# Categories drive the UI color palette (see styles.css):
#   secret    -> red       (API keys, tokens, passwords)
#   pii       -> orange    (names, emails, phones, SSNs)
#   proprietary -> blue    (medical IDs, internal customer ids)
#   hostname  -> purple    (internal hostnames, RFC1918, .corp/.internal)
# ---------------------------------------------------------------------------
CATEGORY_SECRET = "secret"
CATEGORY_PII = "pii"
CATEGORY_PROPRIETARY = "proprietary"
CATEGORY_HOSTNAME = "hostname"


@dataclass
class RedactionEvent:
    id: str
    rule: str
    category: str
    placeholder: str
    start: int
    end: int
    original: str  # NOTE: used internally for rehydration; never sent to cloud.

    def to_public(self) -> dict:
        """Return a dict safe to send to the browser audit panes.

        We expose start/end/category/rule/placeholder, but redact `original`
        to a length-only summary so the UI never re-prints raw secrets.
        """
        return {
            "id": self.id,
            "rule": self.rule,
            "category": self.category,
            "placeholder": self.placeholder,
            "start": self.start,
            "end": self.end,
            "length": len(self.original),
        }


# ---------------------------------------------------------------------------
# gitleaks-style regex pack (trimmed to the high-signal patterns).
# Each entry: (rule_name, category, regex)
# ---------------------------------------------------------------------------
_SECRET_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("aws_access_key", CATEGORY_SECRET, re.compile(r"\b((?:AKIA|ASIA)[A-Z0-9]{16})\b")),
    ("aws_secret_key", CATEGORY_SECRET, re.compile(r"(?i)aws(.{0,20})?(secret|access)?[\s_-]*key[\s_-]*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?")),
    ("github_token", CATEGORY_SECRET, re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,255})\b")),
    ("github_oauth", CATEGORY_SECRET, re.compile(r"\bgho_[A-Za-z0-9]{36,255}\b")),
    ("openai_key", CATEGORY_SECRET, re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_key", CATEGORY_SECRET, re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("stripe_live_key", CATEGORY_SECRET, re.compile(r"\b(sk|pk|rk)_live_[A-Za-z0-9]{20,}\b")),
    ("stripe_test_key", CATEGORY_SECRET, re.compile(r"\b(sk|pk|rk)_test_[A-Za-z0-9]{20,}\b")),
    ("slack_token", CATEGORY_SECRET, re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", CATEGORY_SECRET, re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", CATEGORY_SECRET, re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("private_key_pem", CATEGORY_SECRET, re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("certificate_pem", CATEGORY_SECRET, re.compile(r"-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----")),
    # Conservative-bias literal-substring catcher (Decision 1).
    ("kv_secret_assignment", CATEGORY_SECRET, re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|pwd|token|credential|auth)\b\s*[:=]\s*['\"]?([^\s'\"`,;]{8,})['\"]?")),
]

# Internal hostnames + RFC1918 + common corp suffixes
_HOSTNAME_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("internal_hostname", CATEGORY_HOSTNAME, re.compile(r"\b[a-zA-Z0-9][a-zA-Z0-9-]*\.(internal|corp|local|lan|intra|prod)\b")),
    ("rfc1918_ip", CATEGORY_HOSTNAME, re.compile(r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")),
]

# Proprietary identifiers (demo-flavored — medical record IDs, customer IDs).
_PROPRIETARY_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("medical_record_id", CATEGORY_PROPRIETARY, re.compile(r"\bMRN[-_]?\d{6,10}\b")),
    ("customer_id", CATEGORY_PROPRIETARY, re.compile(r"\bCUST[-_]\d{4,10}\b")),
    ("internal_ticket", CATEGORY_PROPRIETARY, re.compile(r"\b(?:INC|TKT|JIRA)-\d{3,8}\b")),
]

# Catch-all entropy rule: base64-shaped string of length >=32 with high entropy
_BASE64ISH = re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


# ---------------------------------------------------------------------------
# Presidio mapping: PII entity -> category + display rule name
# ---------------------------------------------------------------------------
_PRESIDIO_ENTITIES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "PERSON",
    "US_SSN",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "LOCATION",
    "US_BANK_NUMBER",
    "IBAN_CODE",
    "URL",
    "DATE_TIME",
]


class Redactor:
    """Stateful redactor; reuses Presidio engine across requests."""

    def __init__(self) -> None:
        # Typed as Any: AnalyzerEngine may be unavailable at static-analysis time.
        self._analyzer: Any = None
        if _PRESIDIO_AVAILABLE:
            try:
                self._analyzer = _create_presidio_analyzer()
                model = os.getenv("PRESIDIO_SPACY_MODEL", _DEFAULT_SPACY_MODEL)
                print(f"[redactor] Presidio enabled (spaCy model: {model})")
            except SystemExit as exc:
                # Presidio/spaCy historically called sys.exit from CLI helpers — never kill ASGI.
                print(
                    f"[redactor] Presidio aborted with SystemExit ({exc!r}); "
                    "regex-only redaction — reinstall spaCy model with dev server stopped"
                )
                self._analyzer = None
            except Exception as exc:
                # Fail soft — regex stack still works.
                print(f"[redactor] Presidio init failed ({exc}); falling back to regex-only")
                self._analyzer = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def redact(self, text: str) -> tuple[str, list[RedactionEvent]]:
        """Return (redacted_text, events).

        Algorithm:
          1. Collect spans from regex pack (secrets, hostnames, proprietary).
          2. Collect spans from Presidio (PII).
          3. Collect entropy-based spans (base64-shaped, >=32 chars, entropy>=4).
          4. Resolve overlaps by preferring the highest-priority category
             (secret > pii > proprietary > hostname).
          5. Replace each span left-to-right with `<CATEGORY_NNN>` placeholder.
        """
        events: list[RedactionEvent] = []
        events.extend(self._regex_spans(text, _SECRET_PATTERNS))
        events.extend(self._regex_spans(text, _HOSTNAME_PATTERNS))
        events.extend(self._regex_spans(text, _PROPRIETARY_PATTERNS))
        events.extend(self._presidio_spans(text))
        events.extend(self._entropy_spans(text))

        events = self._resolve_overlaps(events)
        events.sort(key=lambda e: e.start)

        return self._apply_placeholders(text, events)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _regex_spans(
        self,
        text: str,
        patterns: Iterable[tuple[str, str, re.Pattern[str]]],
    ) -> list[RedactionEvent]:
        out: list[RedactionEvent] = []
        for rule, category, pattern in patterns:
            for m in pattern.finditer(text):
                # For multi-group patterns, redact the full match — conservative bias.
                start, end = m.start(), m.end()
                out.append(
                    RedactionEvent(
                        id="",
                        rule=rule,
                        category=category,
                        placeholder="",
                        start=start,
                        end=end,
                        original=text[start:end],
                    )
                )
        return out

    def _presidio_spans(self, text: str) -> list[RedactionEvent]:
        if not self._analyzer:
            return []
        try:
            results = self._analyzer.analyze(
                text=text, entities=_PRESIDIO_ENTITIES, language="en"
            )
        except Exception as exc:
            print(f"[redactor] Presidio analyze failed: {exc}")
            return []
        out: list[RedactionEvent] = []
        for r in results:
            # Presidio confidence varies; conservative-bias means we trust it
            # at >=0.4 (default high threshold ~0.85 misses too much).
            if r.score < 0.4:
                continue
            out.append(
                RedactionEvent(
                    id="",
                    rule=f"presidio_{r.entity_type.lower()}",
                    category=CATEGORY_PII,
                    placeholder="",
                    start=r.start,
                    end=r.end,
                    original=text[r.start : r.end],
                )
            )
        return out

    def _entropy_spans(self, text: str) -> list[RedactionEvent]:
        out: list[RedactionEvent] = []
        for m in _BASE64ISH.finditer(text):
            chunk = m.group(0)
            if _shannon_entropy(chunk) < 4.0:
                continue  # lots of low-entropy >=32 char strings exist (paths, etc.)
            out.append(
                RedactionEvent(
                    id="",
                    rule="high_entropy_blob",
                    category=CATEGORY_SECRET,
                    placeholder="",
                    start=m.start(),
                    end=m.end(),
                    original=chunk,
                )
            )
        return out

    @staticmethod
    def _category_priority(cat: str) -> int:
        return {
            CATEGORY_SECRET: 4,
            CATEGORY_PII: 3,
            CATEGORY_PROPRIETARY: 2,
            CATEGORY_HOSTNAME: 1,
        }.get(cat, 0)

    def _resolve_overlaps(
        self, events: list[RedactionEvent]
    ) -> list[RedactionEvent]:
        """Greedy: keep highest-priority span; drop overlaps."""
        if not events:
            return []
        # Sort by (priority desc, length desc) so we anchor the strongest first.
        events.sort(
            key=lambda e: (-self._category_priority(e.category), -(e.end - e.start))
        )
        kept: list[RedactionEvent] = []
        for e in events:
            if any(not (e.end <= k.start or e.start >= k.end) for k in kept):
                continue
            kept.append(e)
        return kept

    def _apply_placeholders(
        self, text: str, events: list[RedactionEvent]
    ) -> tuple[str, list[RedactionEvent]]:
        if not events:
            return text, []
        # Issue stable placeholders per category, e.g. <SECRET_001>.
        counters: dict[str, int] = {}
        out_parts: list[str] = []
        cursor = 0
        for e in events:
            counters[e.category] = counters.get(e.category, 0) + 1
            placeholder = f"<{e.category.upper()}_{counters[e.category]:03d}>"
            e.id = uuid.uuid4().hex[:12]
            e.placeholder = placeholder
            out_parts.append(text[cursor : e.start])
            out_parts.append(placeholder)
            cursor = e.end
        out_parts.append(text[cursor:])
        return "".join(out_parts), events


# Module-level singleton — Presidio engine is expensive to initialize.
_singleton: Redactor | None = None


def get_redactor() -> Redactor:
    global _singleton
    if _singleton is None:
        _singleton = Redactor()
    return _singleton


def event_to_dict(e: RedactionEvent) -> dict:
    """Full event dict (server-side use only — contains `original`)."""
    return asdict(e)
