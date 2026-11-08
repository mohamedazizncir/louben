"""Payment Agent (sandbox).

Never handles real card numbers: only fake test tokens (tok_visa, tok_declined,
tok_pending). Money moves only with a valid gate_proof, i.e. after the Multisig
Gate collected Payment + Security + Analyst signatures (+ human when risky).
"""
from __future__ import annotations

import asyncio
import re

from agents.security import fraud
from common import config, crypto
from common.a2a import SkillRejected, call, create_agent_app
from common.events import emit
from common.schemas import PaymentResult, new_id
from gate import multisig

# simulated provider: token -> final status
TOKENS = {"tok_visa": "succeeded", "tok_mastercard": "succeeded", "tok_declined": "refused",
          "tok_pending": "pending"}
TOKEN_FORMAT = re.compile(r"^tok_[a-z0-9_]{2,32}$")
CARD_LIKE = re.compile(r"\d[\d \-]{11,}\d")
PENDING_DELAY_S = 20

INTENTS: dict[str, dict] = {}
EXECUTED: set[str] = set()
_bg: set = set()


def reset_state() -> None:
    INTENTS.clear()
    EXECUTED.clear()


def _public(intent: dict) -> dict:
    """Intent fields safe for the event bus (no nonce, token kind only)."""
    return {k: v for k, v in intent.items() if k not in ("nonce",)}


def _verify_gate(payload: bytes, sig: str) -> bool:
    pub = crypto.registry_keys().get("gate")
    return bool(pub) and crypto.verify_bytes(pub, payload, sig)


async def create_intent(data: dict, ctx: dict) -> dict:
    """Build a payment intent (nonce, 5 min expiry, SHA-256 intent_hash) and submit it to the multisig gate."""
    offer = data.get("offer") or {}
    token = str(data.get("payment_token") or "tok_visa")
    if CARD_LIKE.search(token) or not TOKEN_FORMAT.match(token):
        raise SkillRejected("only sandbox payment tokens (tok_*) are accepted, never card numbers")
    intent = multisig.finalize_intent({
        "intent_id": new_id("pi-"), "customer_id": data["customer_id"], "product_id": offer["product_id"],
        "amount": float(offer["final_price"]), "discount_pct": float(offer.get("discount_pct", 0)),
        "installments": int(offer.get("installments", 1)), "payment_token": token,
        "segment": data.get("segment") or "individual"})
    INTENTS[intent["intent_id"]] = intent
    await emit("payment.intent_created", {k: v for k, v in _public(intent).items() if k != "payment_token"})
    return await call("gate", "submit", intent, timeout=20)


async def sign(data: dict, ctx: dict) -> dict:
    """Co-sign only if the amount equals catalog price minus discount, the token is a sandbox token and the hash matches."""
    product = config.product(data.get("product_id", ""))
    mismatch = product and fraud.amount_mismatch(float(data.get("amount", -1)), float(product["list_price"]),
                                                 float(data.get("discount_pct", 0) or 0))
    if multisig.compute_intent_hash(data) != data.get("intent_hash"):
        decision, reason = "refuse", "intent_hash does not match the intent fields"
    elif not product:
        decision, reason = "refuse", "unknown product"
    elif mismatch:
        decision, reason = "refuse", mismatch.reason
    elif not TOKEN_FORMAT.match(str(data.get("payment_token", ""))):
        decision, reason = "refuse", "invalid payment token format"
    else:
        decision, reason = "approve", f"amount matches catalog ({data['amount']:g} TND)"
    body = multisig.signing_payload_dict(data["intent_id"], data["intent_hash"], "payment", decision)
    return {**body, "reason": reason, "signature_b64": crypto.sign_obj("payment", body)}


async def _emit_status(intent: dict, status: str, ref: str) -> dict:
    res = PaymentResult(intent_id=intent["intent_id"], status=status, provider="simulated", provider_ref=ref)
    await emit("payment.status", {**res.model_dump(), "amount": intent["amount"], "customer_id": intent["customer_id"],
                                  "product_id": intent["product_id"], "segment": intent.get("segment"),
                                  "discount_pct": intent.get("discount_pct", 0),
                                  "installments": intent.get("installments", 1),
                                  "payment_token_kind": intent.get("payment_token")},
               severity="warning" if status == "refused" else "info")
    return res.model_dump()


async def _settle_later(intent: dict, ref: str) -> None:
    await asyncio.sleep(PENDING_DELAY_S)
    await _emit_status(intent, "succeeded", ref)


async def execute(data: dict, ctx: dict) -> dict:
    """Execute a sandbox payment. Requires a valid gate_proof over the intent hash and all signatures."""
    intent = INTENTS.get(data.get("intent_id", ""))
    if not intent:
        raise SkillRejected("unknown intent")
    sigs = data.get("signatures") or []
    if not multisig.verify_gate_proof(data.get("gate_proof", ""), intent["intent_hash"], sigs, _verify_gate):
        await emit("security.alert", {"type": "fake_approval", "severity": "critical", "customer_id": intent["customer_id"],
                                      "target": "payment", "details": {"intent_id": intent["intent_id"],
                                                                       "reason": "invalid gate proof"}},
                   severity="critical")
        raise SkillRejected("invalid gate proof")
    if intent["intent_id"] in EXECUTED:
        await emit("security.alert", {"type": "replay", "severity": "high", "customer_id": intent["customer_id"],
                                      "target": "payment", "details": {"intent_id": intent["intent_id"],
                                                                       "reason": "intent already executed"}},
                   severity="warning")
        raise SkillRejected("intent already executed")
    EXECUTED.add(intent["intent_id"])
    status = TOKENS.get(intent.get("payment_token", ""), "refused")
    ref = new_id("sim_")
    res = await _emit_status(intent, status, ref)
    if status == "pending":
        t = asyncio.create_task(_settle_later(intent, ref))
        _bg.add(t)
        t.add_done_callback(_bg.discard)
    return res


app = create_agent_app("payment", "Payment Agent: sandbox payments, statuses, multisig co-signer", {
    "create_intent": create_intent, "sign": sign, "execute": execute})
