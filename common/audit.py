"""Hash chained, append only audit log.

Owner: B after CP0 (first version written by A in phase 0). Keep the function signatures.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading

from common.config import DATA_DIR
from common.crypto import canonical, sha256_hex

DB = DATA_DIR / "audit.db"
_lock = threading.Lock()
GENESIS = "0" * 64
_EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+)")


def mask(obj):
    """Mask emails anywhere in the event before storing."""
    if isinstance(obj, str):
        return _EMAIL.sub(r"\1***@\2", obj)
    if isinstance(obj, dict):
        return {k: mask(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v) for v in obj]
    return obj


def _conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.execute("""CREATE TABLE IF NOT EXISTS audit(
        seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT, ts TEXT, source TEXT, type TEXT,
        severity TEXT, event_json TEXT, prev_hash TEXT, hash TEXT)""")
    return c


def append(event: dict) -> dict:
    event = mask(event)
    with _lock:
        c = _conn()
        row = c.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        prev = row[0] if row else GENESIS
        body = canonical(event)
        h = sha256_hex(prev.encode() + body)
        c.execute("INSERT INTO audit(event_id, ts, source, type, severity, event_json, prev_hash, hash) VALUES(?,?,?,?,?,?,?,?)",
                  (event.get("event_id"), event.get("ts"), event.get("source"), event.get("type"),
                   event.get("severity"), body.decode(), prev, h))
        c.commit()
        c.close()
    return {**event, "hash": h}


def list_events(limit: int = 200, type: str | None = None, source: str | None = None) -> list[dict]:
    c = _conn()
    q, args = "SELECT seq, event_json, prev_hash, hash FROM audit", []
    conds = []
    if type:
        conds.append("type LIKE ?"); args.append(type.replace("*", "%"))
    if source:
        conds.append("source = ?"); args.append(source)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY seq DESC LIMIT ?"; args.append(limit)
    rows = c.execute(q, args).fetchall()
    c.close()
    return [{"seq": s, **json.loads(e), "prev_hash": p, "hash": h} for s, e, p, h in rows]


def verify() -> dict:
    """Walk the chain. Returns {ok, checked, broken_at}."""
    c = _conn()
    prev, n = GENESIS, 0
    for seq, body, p, h in c.execute("SELECT seq, event_json, prev_hash, hash FROM audit ORDER BY seq"):
        n += 1
        if p != prev or sha256_hex(prev.encode() + body.encode()) != h:
            c.close()
            return {"ok": False, "checked": n, "broken_at": seq}
        prev = h
    c.close()
    return {"ok": True, "checked": n, "broken_at": None}
