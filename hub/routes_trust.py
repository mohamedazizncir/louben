"""Trust API for the UI (human login, gate queue, red team, rules, audit).

"""
from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from common import a2a, audit, config, crypto
from common.a2a import A2AError
from common.events import emit
from gate import multisig

router = APIRouter(prefix="/api")


def _err(e: A2AError, status: int = 502):
    return JSONResponse({"error": e.message, "state": e.state, "data": e.data}, status_code=status)


def _human_ok(token: str) -> bool:
    try:
        claims = crypto.verify_jwt(token or "", aud="gate")
        return claims.get("iss") == "human" and "human:approve" in claims.get("scope", [])
    except ValueError:
        return False


_failed_logins: list[float] = []
MAX_FAILED, LOCKOUT_S = 5, 60


@router.post("/login")
async def login(request: Request):
    """PIN -> human JWT. 5 wrong PINs lock the login for 60 s (stops brute force of a 4 digit PIN)."""
    body = await request.json()
    now = time.time()
    _failed_logins[:] = [t for t in _failed_logins if now - t < LOCKOUT_S]
    if len(_failed_logins) >= MAX_FAILED:
        return JSONResponse({"error": f"too many wrong PINs, wait {LOCKOUT_S}s"}, status_code=429)
    if not hmac.compare_digest(str(body.get("pin", "")), str(config.HUMAN_PIN)):
        _failed_logins.append(now)
        await emit("security.alert", {"type": "fake_approval", "severity": "medium" if len(_failed_logins) < 3 else "high",
                                      "details": {"reason": f"wrong dashboard PIN ({len(_failed_logins)}/{MAX_FAILED})"}},
                   severity="warning")
        return JSONResponse({"error": "wrong PIN"}, status_code=401)
    _failed_logins.clear()
    # token lives in browser memory only (trust.js), never in localStorage
    token = crypto.sign_jwt("human", ["gate", "security"], ["human:approve"], ttl=1800,
                            extra={"sub": str(body.get("name") or "operator")[:40]})
    return {"token": token, "expires_in": 1800}


@router.get("/gate/pending")
async def gate_pending():
    try:
        return await a2a.call("gate", "pending", {}, quiet=True)
    except A2AError as e:
        return _err(e)


@router.post("/gate/decision")
async def gate_decision(request: Request):
    """Human key = PIN-backed JWT + an Ed25519 'human' signature over the exact intent_hash."""
    body = await request.json()
    token = body.get("token", "")
    if not _human_ok(token):
        await emit("security.alert", {"type": "fake_approval", "severity": "high", "target": "gate",
                                      "details": {"reason": "gate decision without a valid human login",
                                                  "intent_id": body.get("intent_id")}}, severity="warning")
        return JSONResponse({"error": "human login required"}, status_code=401)
    intent_id = body.get("intent_id")
    decision = "approve" if body.get("decision", "approve") == "approve" else "refuse"
    try:
        items = (await a2a.call("gate", "pending", {}, quiet=True)).get("items", [])
        p = next((x for x in items if x["intent"]["intent_id"] == intent_id), None)
        if p is None:
            return JSONResponse({"error": "unknown or already decided intent"}, status_code=404)
        sig_body = multisig.signing_payload_dict(intent_id, p["intent"]["intent_hash"], "human", decision)
        human_sig = {**sig_body, "reason": "operator decision", "signature_b64": crypto.sign_obj("human", sig_body)}
        return await a2a.call("gate", "human_decision", {"intent_id": intent_id, "decision": decision,
                                                         "human_jwt": token, "human_signature": human_sig},
                              timeout=30)
    except A2AError as e:
        return _err(e, 403 if e.state in ("rejected", "refused") else 502)


@router.post("/redteam/run")
async def redteam_run(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        return await a2a.call("redteam", "run_campaign", {"attacks": body.get("attacks", "all")}, timeout=90)
    except A2AError as e:
        return _err(e)


@router.get("/redteam/score")
async def redteam_score():
    try:
        return await a2a.call("redteam", "score", {}, quiet=True)
    except A2AError as e:
        return _err(e)


@router.get("/rules")
async def rules():
    try:
        return await a2a.call("security", "list_rules", {}, quiet=True)
    except A2AError as e:
        return _err(e)


@router.post("/rules/decision")
async def rules_decision(request: Request):
    body = await request.json()
    if not _human_ok(body.get("token", "")):
        return JSONResponse({"error": "human login required"}, status_code=401)
    try:
        return await a2a.call("security", "rule_decision", {"rule_id": body.get("rule_id"),
                                                            "decision": body.get("decision", "approve")})
    except A2AError as e:
        return _err(e)


@router.get("/audit")
async def audit_list(type: str | None = None, limit: int = 100):
    return {"items": audit.list_events(limit=limit, type=type)}


@router.get("/audit/verify")
async def audit_verify():
    return audit.verify()
