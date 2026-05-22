"""Beat 3 crypto — ed25519 signing + append-only Merkle log.

Honest pitch (Decision 3, premise 1): in production the signing key lives
inside the TEE attestation chain (AWS Nitro / NVIDIA H100). For the v1
prototype, we use software keys with the same protocol — the verifier is
real, only the key custody is software-rooted.

Public API:
    ed25519_keypair()         -> (signing_key_b64, verify_key_b64)
    sign(payload_dict)        -> signed envelope dict
    merkle_root(events)       -> hex root of append-only log
    verify_envelope(envelope) -> bool
    verify_log(events, root)  -> bool
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Iterable

from nacl import signing, encoding, exceptions as nacl_exc

# ---------------------------------------------------------------------------
# Per-session key material. Stored under audit-keys/ at repo root so the
# verifier page can fetch the public key.
# ---------------------------------------------------------------------------
_KEY_DIR = Path(__file__).resolve().parent.parent / "audit-keys"
_KEY_DIR.mkdir(exist_ok=True)
_PRIV_PATH = _KEY_DIR / "session.signing.key"
_PUB_PATH = _KEY_DIR / "session.verify.key"

_signer: signing.SigningKey | None = None
_verifier: signing.VerifyKey | None = None


def _load_or_create_keys() -> tuple[signing.SigningKey, signing.VerifyKey]:
    if _PRIV_PATH.exists() and _PUB_PATH.exists():
        try:
            sk = signing.SigningKey(_PRIV_PATH.read_bytes(), encoder=encoding.RawEncoder)
            vk = sk.verify_key
            return sk, vk
        except Exception as exc:  # corrupt key file — regenerate
            print(f"[crypto] existing key invalid ({exc}); regenerating")
    sk = signing.SigningKey.generate()
    vk = sk.verify_key
    _PRIV_PATH.write_bytes(bytes(sk))
    _PUB_PATH.write_bytes(bytes(vk))
    # Restrict permissions where possible (no-op on Windows).
    try:
        os.chmod(_PRIV_PATH, 0o600)
    except Exception:
        pass
    return sk, vk


def _ensure_keys() -> None:
    global _signer, _verifier
    if _signer is None or _verifier is None:
        _signer, _verifier = _load_or_create_keys()


def public_key_b64() -> str:
    """Base64 verify key, served to the verifier page."""
    _ensure_keys()
    assert _verifier is not None
    return base64.b64encode(bytes(_verifier)).decode("ascii")


def ed25519_keypair() -> tuple[str, str]:
    """Return (signing_key_b64, verify_key_b64). Mostly for tests/preflight."""
    _ensure_keys()
    assert _signer is not None and _verifier is not None
    return (
        base64.b64encode(bytes(_signer)).decode("ascii"),
        base64.b64encode(bytes(_verifier)).decode("ascii"),
    )


def _canonical_json(obj: dict) -> bytes:
    """Stable serialization for signing — sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(payload: dict) -> dict:
    """Sign a payload dict and return an envelope:

        {
          "payload": {...},
          "payload_hash": "<sha256 hex>",
          "signature": "<base64>",
          "verify_key": "<base64>",
          "alg": "ed25519",
          "ts": <unix epoch seconds>
        }
    """
    _ensure_keys()
    assert _signer is not None
    body = _canonical_json(payload)
    sig = _signer.sign(body).signature
    return {
        "payload": payload,
        "payload_hash": hashlib.sha256(body).hexdigest(),
        "signature": base64.b64encode(sig).decode("ascii"),
        "verify_key": public_key_b64(),
        "alg": "ed25519",
        "ts": int(time.time()),
    }


def verify_envelope(envelope: dict) -> bool:
    try:
        body = _canonical_json(envelope["payload"])
        if hashlib.sha256(body).hexdigest() != envelope.get("payload_hash"):
            return False
        vk = signing.VerifyKey(
            base64.b64decode(envelope["verify_key"]),
            encoder=encoding.RawEncoder,
        )
        sig = base64.b64decode(envelope["signature"])
        vk.verify(body, sig)
        return True
    except (nacl_exc.BadSignatureError, KeyError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Append-only Merkle log
# ---------------------------------------------------------------------------
def _hash_leaf(envelope: dict) -> bytes:
    return hashlib.sha256(b"\x00" + _canonical_json(envelope)).digest()


def _hash_pair(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def merkle_root(envelopes: Iterable[dict]) -> str:
    """Return hex Merkle root over a sequence of signed envelopes.

    Empty input -> 64 zero-chars (sentinel). Odd levels duplicate the last node.
    """
    layer: list[bytes] = [_hash_leaf(e) for e in envelopes]
    if not layer:
        return "0" * 64
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        layer = [_hash_pair(layer[i], layer[i + 1]) for i in range(0, len(layer), 2)]
    return layer[0].hex()


def verify_log(envelopes: list[dict], expected_root: str) -> dict:
    """Verify every envelope's signature AND that the recomputed root matches.

    Returns a structured result for the verifier UI.
    """
    bad = [i for i, e in enumerate(envelopes) if not verify_envelope(e)]
    recomputed = merkle_root(envelopes)
    return {
        "ok": not bad and recomputed == expected_root,
        "events": len(envelopes),
        "bad_signatures": bad,
        "recomputed_root": recomputed,
        "expected_root": expected_root,
        "match": recomputed == expected_root,
    }
