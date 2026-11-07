"""Multisig Gate. PHASE 0 STUB written by A, owned by B after CP0.

A payment needs 3 agent signatures (payment, security, analyst) + a human key when risky.
"""
from __future__ import annotations

import asyncio

from common import config, crypto
from common.a2a import A2AError, SkillRejected, call, create_agent_app
from common.events import emit
from common.schemas import GateDecision, PaymentIntent, Signature

PENDING: dict[str, dict] = {}
USED_NONCES: set[str] = set()
SIGNERS = ["payment", "security", "analyst"]


def intent_hash(intent: dict) -> str:
    return crypto.sha256_hex(crypto.canonical({k: v for k, v in intent.items() if k != "intent_hash"}))


def sig_ok(s: dict) -> bool:
    return crypto.verify_obj(s["signer"], {"intent_id": s["intent_id"], "intent_hash": s["intent_hash"],
                                           "signer": s["signer"], "decision": s["decision"]}, s.get("signature_b64", ""))


async def _collect(intent: dict) -> list[dict]:
    async def one(signer):
        try:
            s = await call(signer, "sign", intent)
            if not sig_ok(s) or s["intent_hash"] != intent["intent_hash"]:
                s = {**s, "decision": "refuse", "reason": "invalid signature"}
        except A2AError as e:
            s = Signature(intent_id=intent["intent_id"], intent_hash=intent["intent_hash"], signer=signer,
                          decision="refuse", reason=f"unreachable: {e.message}").model_dump()
        await emit("gate.signature", {"intent_id": intent["intent_id"], "signer": signer, "decision": s["decision"],
                                      "reason": s.get("reason", "")})
        return s
    return list(await asyncio.gather(*(one(s) for s in SIGNERS)))


async def _execute(intent: dict, sigs: list[dict]) -> dict:
    proof = crypto.sign_obj("gate", {"intent_id": intent["intent_id"], "intent_hash": intent["intent_hash"], "approved": True})
    res = await call("payment", "execute", {"intent_id": intent["intent_id"], "gate_proof": proof})
    await emit("gate.approved", {"intent_id": intent["intent_id"], "amount": intent["amount"],
                                 "payment_status": res.get("status")})
    return GateDecision(intent_id=intent["intent_id"], status="executed", signatures=[Signature(**s) for s in sigs],
                        payment_status=res.get("status")).model_dump()


async def submit(data: dict, ctx: dict) -> dict:
    """Collect the 3 agent signatures, ask a human when risky, then execute."""
    intent = PaymentIntent(**data).model_dump()
    if intent_hash(intent) != intent["intent_hash"]:
        await emit("security.alert", {"type": "tampering", "severity": "critical", "customer_id": intent["customer_id"],
                                      "details": {"intent_id": intent["intent_id"]}}, severity="critical")
        raise SkillRejected("intent hash mismatch (tampering)")
    if intent["nonce"] in USED_NONCES:
        await emit("security.alert", {"type": "replay", "severity": "critical", "customer_id": intent["customer_id"],
                                      "details": {"intent_id": intent["intent_id"]}}, severity="critical")
        raise SkillRejected("nonce already used (replay)")
    USED_NONCES.add(intent["nonce"])

    sigs = await _collect(intent)
    refused = [s for s in sigs if s["decision"] != "approve"]
    if refused:
        await emit("gate.rejected", {"intent_id": intent["intent_id"], "customer_id": intent["customer_id"],
                                     "amount": intent["amount"], "product_id": intent["product_id"],
                                     "reasons": [f"{s['signer']}: {s.get('reason')}" for s in refused]}, severity="warning")
        return GateDecision(intent_id=intent["intent_id"], status="rejected",
                            signatures=[Signature(**s) for s in sigs]).model_dump()

    policy = config.load_json("policy.json")
    reasons = []
    if intent["amount"] > float(policy.get("human_threshold", 1000)):
        reasons.append(f"amount {intent['amount']} TND > {policy.get('human_threshold')} TND")
    if intent["discount_pct"] > float(policy.get("human_discount_pct", 10)):
        reasons.append(f"discount {intent['discount_pct']}% > {policy.get('human_discount_pct')}%")
    if reasons:
        PENDING[intent["intent_id"]] = {"intent": intent, "signatures": sigs, "reason": "; ".join(reasons)}
        await emit("gate.pending_human", {"intent_id": intent["intent_id"], "customer_id": intent["customer_id"],
                                          "amount": intent["amount"], "product_id": intent["product_id"],
                                          "reason": "; ".join(reasons)}, severity="warning")
        return GateDecision(intent_id=intent["intent_id"], status="pending_human", human_required=True,
                            human_reason="; ".join(reasons), signatures=[Signature(**s) for s in sigs]).model_dump()
    return await _execute(intent, sigs)


async def pending(data: dict, ctx: dict) -> dict:
    """List intents waiting for a human key."""
    return {"items": [{"intent": p["intent"], "signatures": p["signatures"], "reason": p["reason"]} for p in PENDING.values()]}


async def human_decision(data: dict, ctx: dict) -> dict:
    """Apply the human key (requires a valid human JWT with scope human:approve)."""
    try:
        claims = crypto.verify_jwt(data.get("human_jwt", ""), aud="gate")
        if claims.get("iss") != "human" or "human:approve" not in claims.get("scope", []):
            raise ValueError("not a human approval token")
    except ValueError as e:
        await emit("security.alert", {"type": "fake_approval", "severity": "critical",
                                      "details": {"intent_id": data.get("intent_id"), "reason": str(e)}}, severity="critical")
        raise SkillRejected(f"human approval refused: {e}")
    p = PENDING.pop(data.get("intent_id", ""), None)
    if not p:
        raise SkillRejected("unknown or already decided intent")
    intent, sigs = p["intent"], p["signatures"]
    decision = "approve" if data.get("decision") == "approve" else "refuse"
    human = Signature(intent_id=intent["intent_id"], intent_hash=intent["intent_hash"], signer="human",
                      decision=decision, reason=f"validated by {claims.get('sub', 'operator')}",
                      signature_b64=data.get("human_jwt", "").split(".")[-1]).model_dump()
    await emit("gate.signature", {"intent_id": intent["intent_id"], "signer": "human", "decision": decision,
                                  "reason": human["reason"]})
    if decision != "approve":
        await emit("gate.rejected", {"intent_id": intent["intent_id"], "customer_id": intent["customer_id"],
                                     "amount": intent["amount"], "product_id": intent["product_id"],
                                     "reasons": ["human: rejected"]}, severity="warning")
        return GateDecision(intent_id=intent["intent_id"], status="rejected",
                            signatures=[Signature(**s) for s in sigs + [human]]).model_dump()
    return await _execute(intent, sigs + [human])


app = create_agent_app("gate", "Multisig Gate: 3 agent signatures + human key before any payment", {
    "submit": submit, "pending": pending, "human_decision": human_decision})
