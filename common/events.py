"""Emit events to the hub (fire and forget). Owner: A.

Usage inside any agent:  await emit("payment.status", {...}, severity="info")
The hub stores every event in the audit log and pushes it to the dashboard (SSE).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from common import config
from common.schemas import Event

log = logging.getLogger("events")
SOURCE = {"name": "unknown"}  # set by create_agent_app / hub
_client: httpx.AsyncClient | None = None
_tasks: set = set()


def set_source(name: str) -> None:
    SOURCE["name"] = name


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=3, limits=httpx.Limits(keepalive_expiry=120))
    return _client


async def _post(ev: dict) -> None:
    try:
        await _http().post(f"{config.url('hub')}/events", json=ev)
    except Exception as e:
        log.debug("event not delivered: %s", e)


def make_event(type: str, data: dict | None = None, severity: str = "info", source: str | None = None) -> dict:
    return Event(source=source or SOURCE["name"], type=type, severity=severity, data=data or {}).model_dump()


async def emit(type: str, data: dict | None = None, severity: str = "info", source: str | None = None) -> dict:
    ev = make_event(type, data, severity, source)
    if SOURCE["name"] == "hub" and _local_sink is not None:
        await _local_sink(ev)
    else:
        t = asyncio.create_task(_post(ev))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    return ev


# The hub registers a local sink so its own events skip HTTP.
_local_sink = None


def set_local_sink(fn) -> None:
    global _local_sink
    _local_sink = fn
