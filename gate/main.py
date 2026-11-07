"""Multisig Gate. Owner: B.

No payment moves without 3 agent signatures (Payment, Security, Analyst) over
the same intent_hash, plus a human key when the amount, the discount or the
risk is high (PLAN.md Section 9). Decision logic lives in gate/multisig.py.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from common import config, crypto
from common.a2a import A2AError, SkillRejected, call, create_agent_app
from common.events import emit
from common.schemas import GateDecision, Signature
from gate import multisig

# Once an intent is parked server side, the human has 30 minutes. The 5 minute
# expiry protects the network path (replays), not the operator's reaction time.
HUMAN_WINDOW = timedelta(minutes=30)

PENDING: dict[str, dict] = {}
USED_NONCES: set[str] = set()


def reset_state() -> None:
    PENDING.clear()
    USED_NONCES.clear()


def _verify(signer: str, payload: bytes, sig_b64: str) -> bool:
    pub = crypto.registry_keys().get(signer)
    return bool(pub) and crypto.verify_bytes(pub, payload, sig_b64 or "")


def _decision(intent: dict, status: str, sigs: list[dict], **kw) -> dict:
    return GateDecision(intent_id=intent["intent_id"], status=status,
                        signatures=[Signature(**s) for s in sigs if s.get("signature_b64")], **kw).model_dump()


def _brief(intent: dict) -> dict:
    return {"intent_id": intent["intent_id"], "customer_id": intent["customer_id"],
            "amount": intent["amount"], "product_id": intent["product_id"]}


async def _alert(type_: str, intent: dict, reason: str, severity: str = "critical") -> None:
    await emit("security.alert", {"type": type_, "severity": severity, "customer_id": intent.get("customer_id"),
                                  "target": "gate", "requires_human": False,
                                  "details": {"intent_id": intent.get("intent_id"), "reason": reason}},
               severity="critical" if severity == "critical" else "warning")


async def _reject(intent: dict, sigs: list[dict], reasons: list[str]) -> dict:
    await emit("gate.rejected", {**_brief(intent), "reasons": reasons}, severity="warning")
    return _decision(intent, "rejected", sigs)


async def _collect(intent: dict) -> tuple[list[dict], list[str]]:
    """Ask the 3 signers in parallel. Each signature lights a key on the dashboard."""
    async def one(signer: str):
        try:
            s = await call(signer, "sign", intent)
        except A2AError as e:
            await emit("gate.signature", {"intent_id": intent["intent_id"], "signer": signer,
                                          "decision": "refuse", "reason": f"unreachable: {e.message[:60]}"},
                       severity="warning")
            return None
        await emit("gate.signature", {"intent_id": intent["intent_id"], "signer": signer,
                                      "decision": s.get("decision"), "reason": s.get("reason", ""),
                                      "risk_level": s.get("risk_level")})
        return s
    results = await asyncio.gather(*(one(s) for s in multisig.REQUIRED_SIGNERS))
    unreachable = [n for n, s in zip(multisig.REQUIRED_SIGNERS, results) if s is None]
    return [s for s in results if s is not None], unreachable


async def _execute(intent: dict, sigs: list[dict]) -> dict:
    proof = multisig.make_gate_proof(intent["intent_hash"], sigs, lambda p: crypto.sign_bytes("gate", p))
    try:
        res = await call("payment", "execute", {"intent_id": intent["intent_id"], "gate_proof": proof,
                                                "signatures": sigs})
    except A2AError as e:
        return await _reject(intent, sigs, [f"payment: {e.message}"])
    await emit("gate.approved", {"intent_id": intent["intent_id"], "amount": intent["amount"],
                                 "customer_id": intent["customer_id"], "payment_status": res.get("status")})
    return _decision(intent, "executed", sigs, payment_status=res.get("status"))


async def _report_problems(intent: dict, problems: list[dict]) -> None:
    for p in problems:
        await _alert(p["type"], intent, p["reason"])


async def submit(data: dict, ctx: dict) -> dict:
    """Collect the 3 agent signatures on the intent hash, ask a human when risky, then execute."""
    intent = dict(data)
    if multisig.compute_intent_hash(intent) != intent.get("intent_hash"):
        await _alert("tampering", intent, "intent fields do not match intent_hash")
        raise SkillRejected("intent hash mismatch (tampering)")
    ok, why = multisig.check_freshness(intent, None, USED_NONCES)
    if not ok:
        await _alert("replay", intent, why)
        raise SkillRejected(why)
    USED_NONCES.add(intent["nonce"])

    sigs, unreachable = await _collect(intent)
    if unreachable:  # fail closed
        return await _reject(intent, sigs, [f"{n}: unreachable" for n in unreachable])

    now = datetime.now(timezone.utc)
    ev = multisig.evaluate(intent, sigs, _verify, config.load_json("policy.json"), now=now)
    await _report_problems(intent, ev.problems)
    if ev.status == "rejected" or ev.status == "collecting":
        reasons = [p["reason"] for p in ev.problems] + [
            f"{s['signer']}: {s.get('reason', '')}" for s in sigs if s.get("decision") != "approve"]
        return await _reject(intent, sigs, reasons)
    if ev.status == "pending_human":
        PENDING[intent["intent_id"]] = {"intent": intent, "signatures": sigs, "reason": ev.human_reason,
                                        "received_at": now.isoformat()}
        await emit("gate.pending_human", {**_brief(intent), "reason": ev.human_reason}, severity="warning")
        return _decision(intent, "pending_human", sigs, human_required=True, human_reason=ev.human_reason)
    return await _execute(intent, sigs)


async def pending(data: dict, ctx: dict) -> dict:
    """List intents waiting for a human key."""
    return {"items": [{"intent": {k: v for k, v in p["intent"].items() if k != "nonce"},
                       "signatures": p["signatures"], "reason": p["reason"], "received_at": p["received_at"]}
                      for p in PENDING.values()]}


async def human_decision(data: dict, ctx: dict) -> dict:
    """Apply the human key: a valid human JWT (scope human:approve) AND a human Ed25519 signature on the intent hash."""
    intent_id = data.get("intent_id", "")
    p = PENDING.get(intent_id)
    try:
        claims = crypto.verify_jwt(data.get("human_jwt", ""), aud="gate")
        if claims.get("iss") != "human" or "human:approve" not in claims.get("scope", []):
            raise ValueError("not a human approval token")
    except ValueError as e:
        await _alert("fake_approval", (p or {}).get("intent", {"intent_id": intent_id}), str(e))
        raise SkillRejected(f"human approval refused: {e}")
    if not p:
        raise SkillRejected("unknown or already decided intent")
    intent, sigs = p["intent"], p["signatures"]
    received = datetime.fromisoformat(p["received_at"])
    if datetime.now(timezone.utc) - received > HUMAN_WINDOW:
        PENDING.pop(intent_id, None)
        return await _reject(intent, sigs, ["human window expired"])

    human = data.get("human_signature") or {}
    ev = multisig.evaluate(intent, sigs + [human], _verify, config.load_json("policy.json"), now=received)
    if ev.problems or multisig.HUMAN not in [s.get("signer") for s in ev.signatures]:
        reason = "; ".join(p_["reason"] for p_ in ev.problems) or "missing human signature"
        await _alert("fake_approval", intent, reason)
        raise SkillRejected(f"human signature refused: {reason}")

    PENDING.pop(intent_id, None)
    await emit("gate.signature", {"intent_id": intent_id, "signer": "human", "decision": human.get("decision"),
                                  "reason": f"validated by {claims.get('sub', 'operator')}"})
    all_sigs = sigs + [human]
    if ev.status != "approved":
        return await _reject(intent, all_sigs, ["human: rejected"])
    return await _execute(intent, all_sigs)


app = create_agent_app("gate", "Multisig Gate: 3 agent signatures + human key before any payment", {
    "submit": submit, "pending": pending, "human_decision": human_decision})
