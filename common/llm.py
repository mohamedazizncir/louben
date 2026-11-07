"""LLM access with a deterministic fallback. Owner: A.

Every call MUST pass a fallback so the demo works offline or when the API is slow.
"""
from __future__ import annotations

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
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL,
                              timeout=config.LLM_TIMEOUT, max_retries=0)
    return _client


def _fb(fallback: Fallback):
    return fallback() if callable(fallback) else fallback


async def chat(messages: list[dict], fallback: Fallback, max_tokens: int = 250, temperature: float = 0.4) -> str:
    """Return the model text, or the fallback on any problem."""
    if not available():
        return _fb(fallback)
    try:
        r = await _get_client().chat.completions.create(
            model=config.LLM_MODEL, messages=messages, max_tokens=max_tokens, temperature=temperature)
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
