"""Business API for the UI. Owner: A."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from common import a2a, config
from common.a2a import A2AError
from hub import state

router = APIRouter(prefix="/api")


def _filters(request: Request) -> dict:
    q = request.query_params
    return {k: q.get(k) for k in ("from", "to", "segment", "product_id", "channel") if q.get(k)}


def _err(e: A2AError, status: int = 502):
    return JSONResponse({"error": e.message, "state": e.state, "data": e.data}, status_code=status)


@router.get("/kpis")
async def kpis(request: Request):
    try:
        return await a2a.call("analyst", "kpis", {"filters": _filters(request)}, quiet=True)
    except A2AError as e:
        return _err(e)


@router.get("/drilldown")
async def drilldown(request: Request, kpi: str = "interactions"):
    try:
        return await a2a.call("analyst", "drilldown", {"kpi": kpi, "filters": _filters(request)}, quiet=True)
    except A2AError as e:
        return _err(e)


@router.get("/graph/knowledge")
async def knowledge(request: Request):
    try:
        return await a2a.call("analyst", "knowledge", {"filters": _filters(request)}, quiet=True)
    except A2AError as e:
        return _err(e)


@router.post("/chat")
async def chat(request: Request):
    body = await request.json()
    try:
        return await a2a.call("sales", "chat", {
            "session_id": body.get("session_id"), "customer_id": body.get("customer_id"),
            "text": body.get("text", ""), "channel": body.get("channel", "text"),
            "payment_token": body.get("payment_token")}, timeout=30)
    except A2AError as e:
        return _err(e)


@router.post("/chat/end")
async def chat_end(request: Request):
    body = await request.json()
    try:
        return await a2a.call("sales", "end_session", {"session_id": body.get("session_id")}, timeout=30)
    except A2AError as e:
        return _err(e)


@router.get("/events")
async def list_events(type: str | None = None, limit: int = 200):
    evs = list(state.EVENTS)
    if type:
        prefix = type.rstrip("*")
        evs = [e for e in evs if e["type"].startswith(prefix)]
    return {"items": evs[-limit:]}


@router.get("/catalog")
async def catalog():
    return config.load_json("catalog.json")


@router.get("/agents")
async def agents():
    acl = {k: v for k, v in config.load_json("acl.json").items() if not k.startswith("_")}

    async def one(name):
        try:
            card = await a2a.get_card(name, refresh=True)
            return name, {"card": card, "online": True, "verified": True}
        except Exception as e:
            return name, {"card": None, "online": False, "error": str(e)}

    res = dict(await asyncio.gather(*(one(n) for n in config.AGENTS)))
    for n in res:
        res[n]["can_call"] = acl.get(n, [])
        res[n]["called_by"] = [c for c, rules in acl.items() if any(r.startswith(f"{n}:") for r in rules)]
    return {"agents": res, "acl": acl}


@router.get("/recommendations")
async def recommendations():
    try:
        return await a2a.call("strategy", "list", {}, quiet=True)
    except A2AError as e:
        return _err(e)


@router.post("/recommendations/run")
async def recommendations_run(request: Request):
    try:
        return await a2a.call("strategy", "recommend", {"filters": _filters(request)}, timeout=30)
    except A2AError as e:
        return _err(e)


@router.post("/recommendations/decision")
async def recommendations_decision(request: Request):
    body = await request.json()
    try:
        return await a2a.call("strategy", "decide", {"rec_id": body.get("rec_id"), "decision": body.get("decision"),
                                                       "token": body.get("token")})   # human token, verified by B
    except A2AError as e:
        return _err(e)
