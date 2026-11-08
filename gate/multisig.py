"""Multisig Gate core (rules in SECURITY.md). Pure functions, no I/O.

* intent_hash = SHA-256 of the canonical JSON of the intent fields, so any
  change (amount, discount, token...) changes the hash and breaks signatures.
* Each signer signs {intent_id, intent_hash, signer, decision[, risk_level]},
  the same payload as common.crypto.sign_obj (Analyst, owned by A, relies on it).
* Payment, Security and Analyst must all approve; any refusal rejects.
* A human key is added when the amount, the discount or the risk is high.
* nonce + 5 minute expiry stop replays; the gate_proof lets Payment check
  that the gate really approved before it moves money.

Signing and verification are injected (`sign(payload) -> b64`,
`verify(signer, payload, b64) -> bool`) so this module does not depend on
key storage; common/crypto.py provides them at runtime.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

REQUIRED_SIGNERS = ("payment", "security", "analyst")
HUMAN = "human"
INTENT_TTL = timedelta(minutes=5)
MAX_TTL = timedelta(minutes=5, seconds=5)
MONEY_DECIMALS = 3  # TND has millimes

HASH_FIELDS = ("intent_id", "customer_id", "product_id", "amount", "discount_pct",
               "installments", "payment_token", "nonce", "expires_at", "created_at",
               "segment")  # segment drives the discount cap, so it is hashed too

RISK_ORDER = ["none", "low", "medium", "high", "critical"]
HUMAN_RISK_AT = "medium"

Sign = Callable[[bytes], str]
Verify = Callable[[str, bytes, str], bool]


# --------------------------------------------------------------------------
# Canonical hashing
# --------------------------------------------------------------------------

def _canon(value):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return f"{round(float(value), MONEY_DECIMALS):.{MONEY_DECIMALS}f}"
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return str(value)


def canonical_json(obj) -> str:
    """Sorted keys, no spaces, numbers as fixed 3-decimal strings: the same
    logical intent always gives the same bytes (100 == 100.0)."""
    return json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def compute_intent_hash(intent) -> str:
    payload = {k: _get(intent, k) for k in HASH_FIELDS}
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def finalize_intent(data: dict, now: datetime | None = None) -> dict:
    """Add nonce, created_at, expires_at and intent_hash to an intent draft."""
    now = _now(now)
    intent = dict(data)
    intent.setdefault("nonce", secrets.token_hex(16))
    intent["created_at"] = now.isoformat()
    intent["expires_at"] = (now + INTENT_TTL).isoformat()
    intent["intent_hash"] = compute_intent_hash(intent)
    return intent


# --------------------------------------------------------------------------
# Freshness, human rules
# --------------------------------------------------------------------------

def check_freshness(intent, now: datetime | None, used_nonces: set) -> tuple[bool, str]:
    now = _now(now)
    if _get(intent, "nonce") in used_nonces:
        return False, "replay: nonce already used"
    try:
        created, expires = _dt(_get(intent, "created_at")), _dt(_get(intent, "expires_at"))
    except (TypeError, ValueError):
        return False, "malformed timestamps"
    if now > expires:
        return False, "expired intent"
    if expires - created > MAX_TTL:
        return False, "expiry window longer than 5 minutes"
    return True, "fresh"


def human_requirement(intent, policy: dict, risk_level: str = "none") -> tuple[bool, str | None]:
    reasons = []
    threshold = float(policy.get("human_threshold", 1000))
    max_disc = float(policy.get("human_discount_pct", 10))
    amount = float(_get(intent, "amount", 0) or 0)
    discount = float(_get(intent, "discount_pct", 0) or 0)
    if amount > threshold:
        reasons.append(f"amount {amount:g} TND > {threshold:g} TND")
    if discount > max_disc:
        reasons.append(f"discount {discount:g}% > {max_disc:g}%")
    if RISK_ORDER.index(risk_level if risk_level in RISK_ORDER else "none") >= RISK_ORDER.index(HUMAN_RISK_AT):
        reasons.append(f"risk {risk_level}")
    return (True, "; ".join(reasons)) if reasons else (False, None)


# --------------------------------------------------------------------------
# Signatures
# --------------------------------------------------------------------------

def signing_payload_dict(intent_id: str, intent_hash: str, signer: str, decision: str,
                         risk_level: str | None = None) -> dict:
    body = {"intent_id": intent_id, "intent_hash": intent_hash, "signer": signer,
            "decision": decision}
    if risk_level is not None:
        body["risk_level"] = risk_level  # signed, so it cannot be stripped in transit
    return body


def signing_payload(intent_id: str, intent_hash: str, signer: str, decision: str,
                    risk_level: str | None = None) -> bytes:
    """Byte-identical to common.crypto.canonical(signing_payload_dict(...))."""
    body = signing_payload_dict(intent_id, intent_hash, signer, decision, risk_level)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def make_signature(intent, signer: str, decision: str, reason: str,
                   sign: Sign, now: datetime | None = None,
                   risk_level: str | None = None) -> dict:
    """Build a Signature dict (common/schemas.py) over the intent's hash."""
    intent_id, intent_hash = _get(intent, "intent_id"), _get(intent, "intent_hash")
    payload = signing_payload(intent_id, intent_hash, signer, decision, risk_level)
    sig = {"intent_id": intent_id, "intent_hash": intent_hash, "signer": signer,
           "decision": decision, "reason": reason, "signature_b64": sign(payload),
           "ts": _now(now).isoformat()}
    if risk_level is not None:
        sig["risk_level"] = risk_level
    return sig


def _risk_of(sig) -> str:
    """Only the signed risk_level counts; free text in `reason` is ignored."""
    level = _get(sig, "risk_level")
    return level if level in RISK_ORDER else "none"


def _max_risk(levels: Iterable[str]) -> str:
    return max(levels, key=RISK_ORDER.index, default="none")


@dataclass
class GateEvaluation:
    intent_id: str
    status: str  # collecting | pending_human | approved | rejected
    signatures: list[dict]
    human_required: bool = False
    human_reason: str | None = None
    risk_level: str = "none"
    problems: list[dict] = field(default_factory=list)  # [{type, signer?, reason}]

    def to_decision(self) -> dict:
        """GateDecision fields only (common/schemas.py)."""
        return {"intent_id": self.intent_id, "status": self.status,
                "signatures": self.signatures, "human_required": self.human_required,
                "human_reason": self.human_reason}


def evaluate(intent, signatures: list, verify: Verify, policy: dict,
             risk_level: str = "none", now: datetime | None = None) -> GateEvaluation:
    """Decide the gate status from the intent and the signatures collected so far."""
    intent_id = _get(intent, "intent_id")
    stated_hash = _get(intent, "intent_hash")
    real_hash = compute_intent_hash(intent)
    problems: list[dict] = []
    valid: dict[str, list[dict]] = {}

    if stated_hash != real_hash:
        problems.append({"type": "tampering", "reason": "intent fields do not match intent_hash"})

    try:
        if _now(now) > _dt(_get(intent, "expires_at")):
            problems.append({"type": "replay", "reason": "expired intent"})
    except (TypeError, ValueError):
        problems.append({"type": "replay", "reason": "malformed expires_at"})

    for sig in signatures:
        signer = _get(sig, "signer")
        if signer not in (*REQUIRED_SIGNERS, HUMAN):
            problems.append({"type": "scope_violation", "signer": signer,
                             "reason": f"'{signer}' is not allowed to sign payments"})
            continue
        if _get(sig, "intent_hash") != real_hash or _get(sig, "intent_id") != intent_id:
            problems.append({"type": "tampering", "signer": signer,
                             "reason": "signature is for a different intent_hash"})
            continue
        payload = signing_payload(intent_id, real_hash, signer,
                                  _get(sig, "decision"), _get(sig, "risk_level"))
        if not verify(signer, payload, _get(sig, "signature_b64", "")):
            kind = "fake_approval" if signer == HUMAN else "spoofed_agent"
            problems.append({"type": kind, "signer": signer,
                             "reason": f"invalid {signer} signature"})
            continue
        valid.setdefault(signer, []).append(sig)

    accepted = [s for group in valid.values() for s in group]
    risk = _max_risk([risk_level if risk_level in RISK_ORDER else "none",
                      *(_risk_of(s) for s in accepted)])
    needed, why = human_requirement(intent, policy, risk)

    def result(status: str) -> GateEvaluation:
        return GateEvaluation(intent_id, status, accepted, needed, why, risk, problems)

    if problems:
        return result("rejected")
    if any(_get(s, "decision") != "approve" for s in accepted):
        return result("rejected")
    if any(s not in valid for s in REQUIRED_SIGNERS):
        return result("collecting")
    if needed:
        return result("approved" if HUMAN in valid else "pending_human")
    return result("approved")


# --------------------------------------------------------------------------
# Gate proof
# --------------------------------------------------------------------------

def gate_proof_payload(intent_hash: str, signatures: list) -> bytes:
    rows = sorted([_get(s, "signer"), _get(s, "decision"), _get(s, "signature_b64")]
                  for s in signatures)
    return canonical_json({"intent_hash": intent_hash, "signatures": rows}).encode()


def make_gate_proof(intent_hash: str, signatures: list, sign: Sign) -> str:
    return sign(gate_proof_payload(intent_hash, signatures))


def verify_gate_proof(proof: str, intent_hash: str, signatures: list,
                      verify_gate: Callable[[bytes, str], bool]) -> bool:
    """Payment's check before execute: gate signed this exact set of
    approvals for this exact intent, and all 3 agents approved."""
    approvers = {_get(s, "signer") for s in signatures
                 if _get(s, "decision") == "approve" and _get(s, "intent_hash") == intent_hash}
    if not set(REQUIRED_SIGNERS) <= approvers:
        return False
    if any(_get(s, "decision") != "approve" for s in signatures):
        return False
    try:
        return bool(verify_gate(gate_proof_payload(intent_hash, signatures), proof))
    except Exception:
        return False
