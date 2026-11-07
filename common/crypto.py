"""Keys, signatures, JWT, signed agent cards.

Owner: B after CP0 (first version written by A in phase 0).
B may rewrite the bodies but must keep these function signatures.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from common.config import KEYS_DIR, SERVICES

# Identities that get a key pair. "rogue" is NOT trusted (absent from registry): red team only.
IDENTITIES = list(SERVICES.keys()) + ["company", "human"]
UNTRUSTED = ["rogue"]


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def canonical(obj) -> bytes:
    """Deterministic JSON bytes used for hashing and signing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- key management
def generate_keys(force: bool = False) -> None:
    KEYS_DIR.mkdir(exist_ok=True)
    registry = {}
    for name in IDENTITIES + UNTRUSTED:
        path = KEYS_DIR / f"{name}.key"
        if force or not path.exists():
            key = Ed25519PrivateKey.generate()
            path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        if name not in UNTRUSTED:
            registry[name] = public_b64(name, _fresh=True)
    (KEYS_DIR / "registry.json").write_text(json.dumps(registry, indent=2))
    load_private.cache_clear()
    registry_keys.cache_clear()


def keys_exist() -> bool:
    return (KEYS_DIR / "registry.json").exists() and all((KEYS_DIR / f"{n}.key").exists() for n in IDENTITIES)


@lru_cache(maxsize=32)
def load_private(name: str) -> Ed25519PrivateKey:
    return serialization.load_pem_private_key((KEYS_DIR / f"{name}.key").read_bytes(), password=None)  # type: ignore


def public_b64(name: str, _fresh: bool = False) -> str:
    key = load_private.__wrapped__(name) if _fresh else load_private(name)
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return b64e(raw)


@lru_cache(maxsize=1)
def registry_keys() -> dict[str, str]:
    return json.loads((KEYS_DIR / "registry.json").read_text())


def _pub(pub_b64: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(b64d(pub_b64))


# ---------------------------------------------------------------- raw signatures
def sign_bytes(name: str, data: bytes) -> str:
    return b64e(load_private(name).sign(data))


def verify_bytes(pub_b64: str, data: bytes, sig_b64: str) -> bool:
    try:
        _pub(pub_b64).verify(b64d(sig_b64), data)
        return True
    except Exception:
        return False


def sign_obj(name: str, obj) -> str:
    return sign_bytes(name, canonical(obj))


def verify_obj(signer: str, obj, sig_b64: str) -> bool:
    pub = registry_keys().get(signer)
    return bool(pub) and verify_bytes(pub, canonical(obj), sig_b64)


# ---------------------------------------------------------------- JWT (EdDSA)
def sign_jwt(iss: str, aud: str, scope: list[str], ttl: int = 60, extra: dict | None = None) -> str:
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "scope": scope, "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
    if extra:
        claims.update(extra)
    return jwt.encode(claims, load_private(iss), algorithm="EdDSA")


def verify_jwt(token: str, aud: str) -> dict:
    """Return claims or raise ValueError. Issuer must be in the trusted registry."""
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except Exception as e:
        raise ValueError(f"malformed token: {e}")
    iss = unverified.get("iss", "")
    pub = registry_keys().get(iss)
    if not pub:
        raise ValueError(f"unknown issuer '{iss}'")
    try:
        return jwt.decode(token, _pub(pub), algorithms=["EdDSA"], audience=aud)
    except Exception as e:
        raise ValueError(f"invalid token from '{iss}': {e}")


# ---------------------------------------------------------------- agent cards
def sign_card(name: str, card: dict) -> dict:
    body = {k: v for k, v in card.items() if k != "signature"}
    body["public_key"] = public_b64(name)
    body["signature"] = sign_obj(name, {k: v for k, v in body.items() if k != "signature"})
    return body


def verify_card(card: dict) -> bool:
    """Card is trusted if its public key matches the registry AND the signature is valid."""
    name = card.get("name", "")
    trusted = registry_keys().get(name)
    if not trusted or trusted != card.get("public_key"):
        return False
    body = {k: v for k, v in card.items() if k != "signature"}
    return verify_bytes(trusted, canonical(body), card.get("signature", ""))
