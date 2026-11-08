"""LLM access with a deterministic fallback. Owner: A.

Every call MUST pass a fallback so the demo works offline or when the API is slow.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from typing import Any, Callable, Union

from common import config

log = logging.getLogger("llm")
Fallback = Union[str, dict, list, Callable[[], Any]]

_client = None


def available() -> bool:
    return bool(config.LLM_API_KEY)


def _get_client():
    global _client
    if _client is None:
        import httpx
        from openai import AsyncOpenAI
        # keep the connection open between conversation turns: a new one may cost a slow DNS lookup (seen: 5 s)
        _client = AsyncOpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL,
                              timeout=config.LLM_TIMEOUT, max_retries=0,
                              http_client=httpx.AsyncClient(limits=httpx.Limits(keepalive_expiry=120)))
    return _client


def _fb(fallback: Fallback):
    return fallback() if callable(fallback) else fallback


async def chat(messages: list[dict], fallback: Fallback, max_tokens: int = 250, temperature: float = 0.4,
               timeout: float | None = None) -> str:
    """Return the model text, or the fallback on any problem. `timeout` overrides LLM_TIMEOUT (spoken replies)."""
    if not available():
        return _fb(fallback)
    extra = {}
    if "gpt-oss" in config.LLM_MODEL:   # reasoning model: keep the hidden reasoning short so the reply fits
        extra = {"reasoning_effort": "low"}
        max_tokens += 200
    try:
        client = _get_client().with_options(timeout=timeout) if timeout else _get_client()
        r = await client.chat.completions.create(
            model=config.LLM_MODEL, messages=messages, max_tokens=max_tokens, temperature=temperature,
            extra_body=extra or None)
        text = (r.choices[0].message.content or "").strip()
        return text or _fb(fallback)
    except Exception as e:  # network, rate limit, timeout...
        log.warning("LLM fallback used: %s", e)
        return _fb(fallback)


async def chat_json(messages: list[dict], fallback: Fallback, max_tokens: int = 400) -> Any:
    """Ask for JSON. Returns parsed JSON or the fallback."""
    if not available():
        return _fb(fallback)
    text = await chat(messages, fallback="", max_tokens=max_tokens, temperature=0.1)
    m = re.search(r"\{.*\}|\[.*\]", text or "", re.S)
    if not m:
        return _fb(fallback)
    try:
        return json.loads(m.group(0))
    except Exception:
        return _fb(fallback)


async def keep_warm(every: float = 40) -> None:
    """Warm the model once, then ping the API (GET /models, no tokens) so the connection and DNS cache stay warm.
    Without it the first reply after a pause can wait seconds for DNS + TLS before the model even starts."""
    if not available():
        return
    await chat([{"role": "user", "content": "ok"}], fallback="", max_tokens=5)
    while True:
        await asyncio.sleep(every)
        try:
            await _get_client().models.list()
        except Exception as e:
            log.debug("keep warm ping failed: %s", e)


def warm_on_start(app) -> None:
    """Run keep_warm() in the background while the FastAPI app runs (does not delay startup)."""
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(keep_warm())
        yield
        task.cancel()
    app.router.lifespan_context = lifespan
