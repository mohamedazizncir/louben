"""Hub: event bus (SSE), audit, dashboard + demo pages, API for the UI. Owner: A.

Routers: routes_business.py (A) and routes_trust.py (B).
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from common import a2a, audit, config, events
from common.schemas import Event
from hub import routes_business, routes_trust, state

log = logging.getLogger("hub")
a2a.SELF["name"] = "hub"
events.set_source("hub")

app = FastAPI(title="Louben hub")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
app.include_router(routes_business.router)
app.include_router(routes_trust.router)

# events the analyst needs to compute KPIs
INGEST = {"interaction.ended", "intel.report", "payment.intent_created", "payment.status", "gate.rejected",
          "gate.pending_human", "security.alert", "strategy.recommendation"}
_bg: set = set()


async def _forward(ev: dict) -> None:
    try:
        await a2a.call("analyst", "ingest", ev, quiet=True, retries=1)
    except Exception as e:
        log.debug("ingest failed: %s", e)


async def publish(ev: dict) -> dict:
    ev = Event(**ev).model_dump()
    stored = audit.append(ev)          # hash chained audit log (masks emails)
    state.EVENTS.append(stored)
    for q in list(state.SUBSCRIBERS):
        if q.qsize() < 900:
            q.put_nowait(stored)
    if ev["type"] in INGEST:
        t = asyncio.create_task(_forward(stored))
        _bg.add(t)
        t.add_done_callback(_bg.discard)
    return stored


events.set_local_sink(publish)


@app.post("/events")
async def post_event(request: Request):
    ev = await request.json()
    stored = await publish(ev)
    return {"ok": True, "event_id": stored["event_id"]}


@app.get("/stream")
async def stream(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    state.SUBSCRIBERS.add(q)

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            state.SUBSCRIBERS.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _page(name: str):
    return FileResponse(config.STATIC_DIR / name, headers={"Cache-Control": "no-store"})


@app.get("/")
async def root():
    return RedirectResponse("/demo")


@app.get("/demo")
async def demo():
    return _page("demo.html")


@app.get("/dashboard")
async def dashboard():
    return _page("index.html")


@app.get("/client")
async def client():
    return _page("client.html")


@app.get("/partner-demo")
async def partner():
    return _page("partner.html")


@app.get("/health")
async def health():
    return {"ok": True, "name": "hub", "subscribers": len(state.SUBSCRIBERS), "events": len(state.EVENTS)}
