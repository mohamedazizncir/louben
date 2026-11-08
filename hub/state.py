"""In-memory hub state shared by both routers."""
from __future__ import annotations

import asyncio
from collections import deque

EVENTS: deque = deque(maxlen=3000)
SUBSCRIBERS: set[asyncio.Queue] = set()
