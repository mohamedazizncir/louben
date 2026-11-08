"""A2A layer: signed agent cards, JSON-RPC message/send, JWT auth on every call.

Server:  app = create_agent_app("sales", "Talks to customers", {"chat": chat_handler, ...})
Client:  data = await call("intel", "analyze", interaction_dict)

Every call is authenticated (EdDSA JWT, least privilege ACL from config/acl.json),
every card is signed and verified, and every call emits an `a2a.call` event (drives the live agent graph).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common import config, crypto, events

log = logging.getLogger("a2a")

SELF = {"name": "unknown"}
Handler = Callable[[dict, dict], Awaitable[Any] | Any]

UNAUTHORIZED = -32001


class A2AError(Exception):
    def __init__(self, message: str, code: int = -32000, state: str = "failed", data: dict | None = None):
        super().__init__(message)
        self.message, self.code, self.state, self.data = message, code, state, data or {}


class SkillRejected(Exception):
    """Raise inside a handler to return a non completed task (state 'rejected' or 'input-required')."""

    def __init__(self, message: str, state: str = "rejected", data: dict | None = None):
        super().__init__(message)
        self.message, self.state, self.data = message, state, data or {}


# ------------------------------------------------------------------ helpers
def _acl() -> dict[str, list[str]]:
    try:
        return config.load_json("acl.json")  # type: ignore[return-value]
    except Exception:
        return {}


def allowed(caller: str, target: str, skill: str) -> bool:
    rules = _acl().get(caller, [])
    return f"{target}:{skill}" in rules or f"{target}:*" in rules


_seen_jti: dict[str, float] = {}


def _jti_fresh(jti: str) -> bool:
    now = time.time()
    for k, exp in list(_seen_jti.items()):
        if exp < now:
            _seen_jti.pop(k, None)
    if jti in _seen_jti:
        return False
    _seen_jti[jti] = now + 120
    return True


def _task(state: str, data: dict | None = None, message: str = "") -> dict:
    return {
        "id": f"task-{uuid.uuid4().hex[:10]}",
        "status": {"state": state, "message": message},
        "artifacts": [{"parts": [{"kind": "data", "data": data or {}}]}],
    }


def _rpc_error(rid, code: int, message: str):
    return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


# ------------------------------------------------------------------ server
def create_agent_app(name: str, description: str, skills: dict[str, Handler], version: str = "1.0.0") -> FastAPI:
    SELF["name"] = name
    events.set_source(name)
    app = FastAPI(title=f"{name} agent")
    card_cache: dict[str, dict] = {}

    def card() -> dict:
        if "c" not in card_cache:
            raw = {
                "name": name,
                "version": version,
                "url": config.url(name) + "/",
                "description": description,
                "protocol": "A2A JSON-RPC 2.0 (message/send)",
                "skills": [{"id": s, "description": (inspect.getdoc(h) or "").split("\n")[0]} for s, h in skills.items()],
                "security": {"auth": "Bearer JWT (EdDSA), audience-bound, 60s, single use", "card": "Ed25519 signed"},
            }
            card_cache["c"] = crypto.sign_card(name, raw)
        return card_cache["c"]

    @app.get("/.well-known/agent-card.json")
    async def agent_card():
        return card()

    @app.get("/health")
    async def health():
        return {"ok": True, "name": name}

    @app.post("/")
    async def rpc(request: Request):
        try:
            body = await request.json()
        except Exception:
            return _rpc_error(None, -32700, "parse error")
        rid = body.get("id")
        if body.get("method") != "message/send":
            return _rpc_error(rid, -32601, "method not found")
        params = body.get("params") or {}
        skill = params.get("skill", "")
        parts = ((params.get("message") or {}).get("parts")) or [{}]
        data = next((p.get("data") for p in parts if p.get("kind") == "data"), {}) or {}

        # ---- authentication + authorization (least privilege)
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else ""
        try:
            claims = crypto.verify_jwt(token, aud=name)
        except Exception as e:
            await events.emit("security.alert", {"type": "spoofed_agent", "severity": "high", "target": name,
                                                 "skill": skill, "details": {"reason": str(e)}}, severity="warning")
            return _rpc_error(rid, UNAUTHORIZED, f"unauthorized: {e}")
        caller = claims.get("iss", "?")
        if not _jti_fresh(claims.get("jti", "")):
            await events.emit("security.alert", {"type": "replay", "severity": "high", "caller": caller,
                                                 "target": name, "skill": skill}, severity="warning")
            return _rpc_error(rid, UNAUTHORIZED, "unauthorized: token replay")
        if f"{name}:{skill}" not in claims.get("scope", []) or not allowed(caller, name, skill):
            await events.emit("security.alert", {"type": "scope_violation", "severity": "high", "caller": caller,
                                                 "target": name, "skill": skill}, severity="warning")
            return _rpc_error(rid, UNAUTHORIZED, f"unauthorized: '{caller}' may not call {name}:{skill}")

        handler = skills.get(skill)
        if handler is None:
            return _rpc_error(rid, -32602, f"unknown skill '{skill}'")
        ctx = {"caller": caller, "claims": claims}
        try:
            out = handler(data, ctx)
            if inspect.isawaitable(out):
                out = await out
            if hasattr(out, "model_dump"):
                out = out.model_dump()
            if isinstance(out, list):
                out = {"items": [o.model_dump() if hasattr(o, "model_dump") else o for o in out]}
            return {"jsonrpc": "2.0", "id": rid, "result": _task("completed", out or {})}
        except SkillRejected as r:
            return {"jsonrpc": "2.0", "id": rid, "result": _task(r.state, r.data, r.message)}
        except Exception as e:
            log.exception("skill %s failed", skill)
            return {"jsonrpc": "2.0", "id": rid, "result": _task("failed", {}, f"{type(e).__name__}: {e}")}

    return app


# ------------------------------------------------------------------ client
_http: httpx.AsyncClient | None = None
_cards: dict[str, dict] = {}


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        # long keep-alive: on Windows a fresh connection after a pause can cost 1-2 s, reuse them between turns
        _http = httpx.AsyncClient(timeout=15, limits=httpx.Limits(keepalive_expiry=120))
    return _http


async def get_card(target: str, verify: bool = True, refresh: bool = False) -> dict:
    if not refresh and target in _cards:
        return _cards[target]
    r = await _client().get(f"{config.url(target)}/.well-known/agent-card.json", timeout=3)
    card = r.json()
    if verify and not crypto.verify_card(card):
        await events.emit("security.alert", {"type": "spoofed_agent", "severity": "critical", "target": target,
                                             "details": {"reason": "agent card signature not trusted"}},
                          severity="critical")
        raise A2AError(f"untrusted agent card for '{target}'", code=UNAUTHORIZED, state="refused")
    _cards[target] = card
    return card


def _summary(skill: str, data: dict, result: dict) -> str:
    for key in ("status", "decision", "allowed", "stage", "immunity_score"):
        if key in result:
            return f"{key}={result[key]}"
    return skill


async def call(target: str, skill: str, data: dict | None = None, *, caller: str | None = None,
               timeout: float = 15, retries: int = 2, quiet: bool = False) -> dict:
    """Call `target.skill` as `caller` (default: this service). Returns the artifact data.

    Raises A2AError when refused, rejected, failed or unreachable.
    quiet=True: do not emit the a2a.call event (used for high frequency internal calls).
    """
    caller = caller or SELF["name"]
    data = data or {}
    t0, started_ms = time.perf_counter(), int(time.time() * 1000)   # started_ms: graph replays calls in causal order
    status, summary, err = "ok", skill, None
    try:
        for attempt in range(retries + 1):
            try:
                await get_card(target, refresh=attempt > 0)
                token = crypto.sign_jwt(caller, target, [f"{target}:{skill}"])
                payload = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send",
                           "params": {"skill": skill, "message": {"role": "agent",
                                                                   "parts": [{"kind": "data", "data": data}]}}}
                r = await _client().post(f"{config.url(target)}/", json=payload,
                                         headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
                break
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                if attempt >= retries:
                    raise A2AError(f"{target} unreachable: {type(e).__name__}", state="error")
                await asyncio.sleep(0.4 * (attempt + 1))
        body = r.json()
        if "error" in body:
            code = body["error"].get("code", -32000)
            status = "refused" if code == UNAUTHORIZED else "error"
            raise A2AError(body["error"].get("message", "error"), code=code, state=status)
        task = body.get("result", {})
        state = task.get("status", {}).get("state", "failed")
        result = (((task.get("artifacts") or [{}])[0].get("parts") or [{}])[0].get("data")) or {}
        if state != "completed":
            status = "refused" if state in ("rejected", "input-required") else "error"
            raise A2AError(task.get("status", {}).get("message", state), state=state, data=result)
        summary = _summary(skill, data, result)
        return result
    except A2AError as e:
        err = e
        if status == "ok":
            status = "refused" if e.code == UNAUTHORIZED or e.state == "refused" else "error"
        summary = e.message[:80]
        raise
    except Exception as e:
        status, summary = "error", f"{type(e).__name__}"
        err = e
        raise A2AError(f"{target}.{skill} failed: {e}", state="error")
    finally:
        if not quiet:
            await events.emit("a2a.call", {
                "from": caller, "to": target, "skill": skill, "status": status,
                "latency_ms": int((time.perf_counter() - t0) * 1000), "summary": summary,
                "started_ms": started_ms,
            }, severity="info" if status == "ok" else "warning")


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
