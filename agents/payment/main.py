"""Payment Agent (sandbox). PHASE 0 STUB written by A, owned by B after CP0.

Never handles real card numbers: only fake tokens (tok_visa, tok_declined, tok_pending).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from common import config, crypto
from common.a2a import SkillRejected, call, create_agent_app
from common.events import emit
from common.schemas import PaymentIntent, PaymentResult, Signature, new_id

INTENTS: dict[str, dict] = {}
TOKENS = {"tok_visa": "succeeded", "tok_mastercard": "succeeded", "tok_declined": "refused", "tok_pending": "pending"}


def intent_hash(intent: dict) -> str:
    body = {k: v for k, v in intent.items() if k not in ("intent_hash",)}
    return crypto.sha256_hex(crypto.canonical(body))


async def create_intent(data: dict, ctx: dict) -> dict:
    """Build a signed-ready payment intent from a validated offer and submit it to the multisig gate."""
    offer = data["offer"]
    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(timespec="seconds")
    intent = PaymentIntent(customer_id=data["customer_id"], product_id=offer["product_id"], amount=offer["final_price"],
                           discount_pct=offer.get("discount_pct", 0), installments=offer.get("installments", 1),
                           payment_token=data.get("payment_token", "tok_visa"), expires_at=expires,
                           segment=data.get("segment")).model_dump()
    intent["intent_hash"] = intent_hash(intent)
    INTENTS[intent["intent_id"]] = intent
    await emit("payment.intent_created", {k: v for k, v in intent.items() if k != "payment_token"})
    return await call("gate", "submit", intent, timeout=20)


async def sign(data: dict, ctx: dict) -> dict:
    """Check amount = catalog price minus discount and token format, then co-sign."""
    intent = PaymentIntent(**data)
    p = config.product(intent.product_id)
    expected = round(p["list_price"] * (1 - intent.discount_pct / 100), 2) if p else -1
    if not p:
        decision, reason = "refuse", "unknown product"
    elif abs(expected - intent.amount) > 0.05:
        decision, reason = "refuse", f"amount {intent.amount} != catalog {expected}"
    elif not intent.payment_token.startswith("tok_"):
        decision, reason = "refuse", "invalid payment token format"
    else:
        decision, reason = "approve", f"amount matches catalog ({expected} TND)"
    sig = Signature(intent_id=intent.intent_id, intent_hash=intent.intent_hash, signer="payment",
                    decision=decision, reason=reason)
    sig.signature_b64 = crypto.sign_obj("payment", {"intent_id": sig.intent_id, "intent_hash": sig.intent_hash,
                                                    "signer": "payment", "decision": decision})
    return sig.model_dump()


async def execute(data: dict, ctx: dict) -> dict:
    """Execute a sandbox payment. Requires a valid gate_proof (multisig approval)."""
    intent = INTENTS.get(data.get("intent_id", "")) or data.get("intent")
    if not intent:
        raise SkillRejected("unknown intent")
    proof_ok = crypto.verify_obj("gate", {"intent_id": intent["intent_id"], "intent_hash": intent["intent_hash"],
                                          "approved": True}, data.get("gate_proof", ""))
    if not proof_ok:
        await emit("security.alert", {"type": "fake_approval", "severity": "critical",
                                      "details": {"intent_id": intent["intent_id"], "reason": "invalid gate proof"}},
                   severity="critical")
        raise SkillRejected("invalid gate proof")
    status = TOKENS.get(intent.get("payment_token", ""), "refused")
    res = PaymentResult(intent_id=intent["intent_id"], status=status, provider="simulated", provider_ref=new_id("sim_"))
    await emit("payment.status", {**res.model_dump(), "amount": intent["amount"], "customer_id": intent["customer_id"],
                                  "product_id": intent["product_id"], "segment": intent.get("segment"),
                                  "discount_pct": intent.get("discount_pct", 0)},
               severity="info" if status != "refused" else "warning")
    return res.model_dump()


app = create_agent_app("payment", "Payment Agent: sandbox payments, statuses, multisig co-signer", {
    "create_intent": create_intent, "sign": sign, "execute": execute})
