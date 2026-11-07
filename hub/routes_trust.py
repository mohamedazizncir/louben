"""Trust API for the UI (human login, gate queue, red team, rules, audit).

PHASE 0 STUB written by A, owned by B after CP0. Keep the routes listed in PLAN.md Section 10.
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from common import a2a, audit, config, crypto
from common.a2a import A2AError
from common.events import emit

router = APIRouter(prefix="/api")


def _err(e: A2AError, status: int = 502):
    return JSONResponse({"error": e.message, "state": e.state, "data": e.data}, status_code=status)


def _human_ok(token: str) -> bool:
    try:
        claims = crypto.verify_jwt(token or "", aud="gate")
        return claims.get("iss") == "human" and "human:approve" in claims.get("scope", [])
    except ValueError:
        return False


@router.post("/login")
async def login(request: Request):
    body = await request.json()
    if not hmac.compare_digest(str(body.get("pin", "")), str(config.HUMAN_PIN)):
        await emit("security.alert", {"type": "fake_approval", "severity": "medium",
                                      "details": {"reason": "wrong dashboard PIN"}}, severity="warning")
        return JSONResponse({"error": "wrong PIN"}, status_code=401)
    token = crypto.sign_jwt("human", "gate", ["human:approve"], ttl=1800, extra={"sub": body.get("name") or "operator"})
    return {"token": token, "expires_in": 1800}


@router.get("/gate/pending")
async def gate_pending():
    try:
        return await a2a.call("gate", "pending", {}, quiet=True)
    except A2AError as e:
        return _err(e)


@router.post("/gate/decision")
async def gate_decision(request: Request):
    body = await request.json()
    try:
        return await a2a.call("gate", "human_decision", {"intent_id": body.get("intent_id"),
                                                         "decision": body.get("decision", "approve"),
                                                         "human_jwt": body.get("token", "")}, timeout=30)
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
