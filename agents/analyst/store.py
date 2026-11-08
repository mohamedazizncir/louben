"""Business data store + KPI computations (pure functions, testable). Owner: A."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from common.config import DATA_DIR

DB_PATH = DATA_DIR / "business.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers(customer_id TEXT PRIMARY KEY, name TEXT, segment TEXT);
CREATE TABLE IF NOT EXISTS interactions(interaction_id TEXT PRIMARY KEY, customer_id TEXT, channel TEXT,
    product_id TEXT, outcome TEXT, segment TEXT, started_at TEXT, ended_at TEXT, n_turns INTEGER, transcript TEXT);
CREATE TABLE IF NOT EXISTS intel(interaction_id TEXT PRIMARY KEY, customer_id TEXT, needs TEXT, objections TEXT,
    motivations TEXT, sentiment REAL, interest REAL, satisfaction INTEGER, segment TEXT, churn_risk REAL, ts TEXT);
CREATE TABLE IF NOT EXISTS payments(intent_id TEXT PRIMARY KEY, customer_id TEXT, product_id TEXT, amount REAL,
    discount_pct REAL, installments INTEGER, status TEXT, reason TEXT, segment TEXT, channel TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS alerts(alert_id TEXT PRIMARY KEY, type TEXT, severity TEXT, source TEXT,
    customer_id TEXT, details TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS recommendations(rec_id TEXT PRIMARY KEY, title TEXT, rationale TEXT, evidence TEXT,
    expected_impact TEXT, status TEXT, ts TEXT);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    c = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ ingest
def ingest(c: sqlite3.Connection, ev: dict) -> bool:
    t, d, ts = ev.get("type", ""), ev.get("data", {}) or {}, ev.get("ts") or _now()
    if str(d.get("customer_id", "")).startswith("redteam-") and not t.startswith("security."):
        return False          # Red Team traffic is not business: keep it out of KPIs and the knowledge graph
    if t == "interaction.ended":
        c.execute("INSERT OR IGNORE INTO customers VALUES(?,?,?)", (d.get("customer_id"), d.get("customer_id"),
                                                                     d.get("segment") or "individual"))
        c.execute("INSERT OR REPLACE INTO interactions VALUES(?,?,?,?,?,?,?,?,?,?)", (
            d.get("interaction_id"), d.get("customer_id"), d.get("channel"), d.get("product_id"), d.get("outcome"),
            d.get("segment") or "individual", d.get("started_at") or ts, d.get("ended_at") or ts,
            len(d.get("turns") or []), json.dumps(d.get("turns") or [], ensure_ascii=False)))
    elif t == "intel.report":
        c.execute("INSERT OR REPLACE INTO intel VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            d.get("interaction_id"), d.get("customer_id"), json.dumps(d.get("needs") or []),
            json.dumps(d.get("objections") or []), json.dumps(d.get("motivations") or []), d.get("sentiment", 0),
            d.get("interest_score", 0), d.get("satisfaction"), d.get("segment"), d.get("churn_risk", 0), ts))
    elif t == "payment.intent_created":
        c.execute("INSERT OR IGNORE INTO payments VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            d.get("intent_id"), d.get("customer_id"), d.get("product_id"), d.get("amount", 0), d.get("discount_pct", 0),
            d.get("installments", 1), "pending", "created", d.get("segment"), d.get("channel"), ts))
    elif t in ("payment.status", "gate.rejected", "gate.pending_human"):
        status = {"gate.rejected": "refused", "gate.pending_human": "pending"}.get(t, d.get("status", "pending"))
        reason = {"gate.rejected": "security", "gate.pending_human": "human_validation"}.get(t, d.get("provider", ""))
        row = c.execute("SELECT intent_id FROM payments WHERE intent_id=?", (d.get("intent_id"),)).fetchone()
        if row:
            c.execute("UPDATE payments SET status=?, reason=?, ts=? WHERE intent_id=?", (status, reason, ts, d.get("intent_id")))
        elif d.get("intent_id"):
            c.execute("INSERT INTO payments VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                d.get("intent_id"), d.get("customer_id"), d.get("product_id"), d.get("amount", 0),
                d.get("discount_pct", 0), d.get("installments", 1), status, reason, d.get("segment"), d.get("channel"), ts))
    elif t == "security.alert":
        det = d.get("details") or {}
        c.execute("INSERT OR IGNORE INTO alerts VALUES(?,?,?,?,?,?,?)", (
            d.get("alert_id") or ev.get("event_id"), d.get("type", "unknown"), d.get("severity", "medium"),
            ev.get("source"), d.get("customer_id") or det.get("customer_id"), json.dumps(d, ensure_ascii=False), ts))
    elif t == "strategy.recommendation":
        for r in d.get("items") or [d]:
            if r.get("rec_id"):
                c.execute("INSERT OR REPLACE INTO recommendations VALUES(?,?,?,?,?,?,?)", (
                    r["rec_id"], r.get("title"), r.get("rationale"), json.dumps(r.get("evidence") or {}),
                    r.get("expected_impact"), r.get("status", "proposed"), ts))
    else:
        return False
    c.commit()
    return True


# ------------------------------------------------------------------ filters
def _where(f: dict, date_col: str, prefix: str = "", cols=("segment", "product_id", "channel")) -> tuple[str, list]:
    conds, args = [], []
    if f.get("from"):
        conds.append(f"substr({prefix}{date_col},1,10) >= ?"); args.append(f["from"][:10])
    if f.get("to"):
        conds.append(f"substr({prefix}{date_col},1,10) <= ?"); args.append(f["to"][:10])
    for k in cols:
        if f.get(k):
            conds.append(f"{prefix}{k} = ?"); args.append(f[k])
    return (" WHERE " + " AND ".join(conds)) if conds else "", args


# ------------------------------------------------------------------ KPIs
def forecast(daily: list[tuple[str, float]], days: int = 7) -> list[dict]:
    if not daily:
        start = date.today()
        return [{"date": (start + timedelta(days=i + 1)).isoformat(), "value": 0.0} for i in range(days)]
    ys = np.array([v for _, v in daily], dtype=float)
    xs = np.arange(len(ys), dtype=float)
    a, b = np.polyfit(xs, ys, 1) if len(ys) >= 2 else (0.0, float(ys[0]))
    last = date.fromisoformat(daily[-1][0])
    return [{"date": (last + timedelta(days=i + 1)).isoformat(),
             "value": round(float(max(0.0, a * (len(ys) + i) + b)), 2)} for i in range(days)]


def kpis(c: sqlite3.Connection, f: dict | None = None) -> dict:
    f = f or {}
    wi, ai = _where(f, "started_at")
    inter = [dict(r) for r in c.execute(f"SELECT * FROM interactions{wi}", ai)]
    ids = {r["interaction_id"] for r in inter}
    intel = [dict(r) for r in c.execute("SELECT * FROM intel") if r["interaction_id"] in ids]
    wp, ap = _where(f, "ts")
    pays = [dict(r) for r in c.execute(f"SELECT * FROM payments{wp}", ap)]
    wa, aa = _where(f, "ts", cols=())
    alerts = [dict(r) for r in c.execute(f"SELECT * FROM alerts{wa}", aa)]

    total = len(inter)
    interested = sum(1 for r in inter if r["outcome"] in ("interested", "purchase_started"))
    st = Counter(p["status"] for p in pays)
    succeeded = st.get("succeeded", 0)
    revenue = round(sum(p["amount"] or 0 for p in pays if p["status"] == "succeeded"), 2)
    obj = Counter(o for r in intel for o in json.loads(r["objections"] or "[]"))
    sats = [r["satisfaction"] for r in intel if r["satisfaction"]]

    by_day: dict[str, dict] = {}
    for r in inter:
        d = (r["started_at"] or "")[:10]
        by_day.setdefault(d, {"date": d, "interactions": 0, "conversions": 0, "revenue": 0.0})
        by_day[d]["interactions"] += 1
    for p in pays:
        d = (p["ts"] or "")[:10]
        by_day.setdefault(d, {"date": d, "interactions": 0, "conversions": 0, "revenue": 0.0})
        if p["status"] == "succeeded":
            by_day[d]["conversions"] += 1
            by_day[d]["revenue"] += p["amount"] or 0
    days = sorted(by_day.values(), key=lambda x: x["date"])
    for d in days:
        d["rate"] = round(d["conversions"] / d["interactions"], 3) if d["interactions"] else 0
        d["revenue"] = round(d["revenue"], 2)

    recs = [dict(r) for r in c.execute("SELECT * FROM recommendations ORDER BY ts DESC LIMIT 5")]
    for r in recs:
        r["evidence"] = json.loads(r["evidence"] or "{}")

    seg = Counter(r["segment"] for r in inter)
    ch = Counter(r["channel"] for r in inter)
    prod_rev = Counter()
    for p in pays:
        if p["status"] == "succeeded":
            prod_rev[p["product_id"]] += p["amount"] or 0

    return {
        "interactions_total": total,
        "interested_total": interested,
        "conversion_rate": round(succeeded / total, 3) if total else 0.0,
        "top_objections": [{"label": k, "count": v} for k, v in obj.most_common(6)],
        "payments": {"succeeded": succeeded, "refused": st.get("refused", 0), "pending": st.get("pending", 0)},
        "revenue_simulated": revenue,
        "avg_satisfaction": round(sum(sats) / len(sats), 2) if sats else None,
        "satisfaction_dist": {str(i): sats.count(i) for i in range(1, 6)},
        "alerts_total": len(alerts),
        "alerts_by_type": dict(Counter(a["type"] for a in alerts)),
        "revenue_forecast_7d": forecast([(d["date"], d["revenue"]) for d in days if d["date"]][-30:]),
        "daily": days[-30:],
        "by_segment": dict(seg),
        "by_channel": dict(ch),
        "revenue_by_product": {k: round(v, 2) for k, v in prod_rev.most_common()},
        "recent_recommendations": recs,
        "filters": f,
    }


# ------------------------------------------------------------------ drill down
def drilldown(c: sqlite3.Connection, kpi: str, f: dict | None = None, limit: int = 200) -> dict:
    f = f or {}
    base, _, arg = kpi.partition(":")
    if base in ("interactions", "interested", "conversion", "segment", "channel", "satisfaction", "objections"):
        w, a = _where(f, "started_at", "i.")
        q = (f"SELECT i.interaction_id, substr(i.started_at,1,16) AS date, i.customer_id, i.segment, i.channel, "
             f"i.product_id, i.outcome, n.objections, n.sentiment, n.satisfaction "
             f"FROM interactions i LEFT JOIN intel n ON n.interaction_id = i.interaction_id{w}")
        extra = []
        if base == "interested":
            extra.append("i.outcome IN ('interested','purchase_started')")
        if base == "conversion":
            extra.append("i.outcome = 'purchase_started'")
        if base == "objections" and arg:
            extra.append("n.objections LIKE ?"); a.append(f'%"{arg}"%')
        if base == "satisfaction" and arg:
            extra.append("n.satisfaction = ?"); a.append(int(arg))
        if base in ("segment", "channel") and arg:
            extra.append(f"i.{base} = ?"); a.append(arg)
        if extra:
            q += (" AND " if w else " WHERE ") + " AND ".join(extra)
        q += " ORDER BY i.started_at DESC LIMIT ?"; a.append(limit)
    elif base in ("payments", "revenue", "product"):
        w, a = _where(f, "ts")
        q = (f"SELECT intent_id, substr(ts,1,16) AS date, customer_id, product_id, amount, discount_pct, installments, "
             f"status, reason, segment FROM payments{w}")
        extra = []
        if base == "revenue":
            extra.append("status = 'succeeded'")
        if base == "payments" and arg:
            extra.append("status = ?"); a.append(arg)
        if base == "product" and arg:
            extra.append("product_id = ?"); a.append(arg)
        if extra:
            q += (" AND " if w else " WHERE ") + " AND ".join(extra)
        q += " ORDER BY ts DESC LIMIT ?"; a.append(limit)
    elif base == "alerts":
        w, a = _where(f, "ts", cols=())
        q = f"SELECT alert_id, substr(ts,1,16) AS date, type, severity, source, customer_id FROM alerts{w}"
        if arg:
            q += (" AND " if w else " WHERE ") + "type = ?"; a.append(arg)
        q += " ORDER BY ts DESC LIMIT ?"; a.append(limit)
    else:
        return {"kpi": kpi, "columns": [], "rows": []}
    cur = c.execute(q, a)
    cols = [d[0] for d in cur.description]
    rows = [list(r) for r in cur.fetchall()]
    return {"kpi": kpi, "columns": cols, "rows": rows}


# ------------------------------------------------------------------ knowledge graph
def knowledge(c: sqlite3.Connection, f: dict | None = None, max_customers: int = 35) -> dict:
    f = f or {}
    w, a = _where(f, "started_at")
    inter = [dict(r) for r in c.execute(f"SELECT * FROM interactions{w} ORDER BY started_at DESC LIMIT ?",
                                        a + [max_customers * 2])]
    cust_ids = list(dict.fromkeys(r["customer_id"] for r in inter))[:max_customers]
    cs = set(cust_ids)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid, ntype, label, **extra):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype, "label": label, **extra}

    from common.config import catalog
    names = {p["product_id"]: p["name"] for p in catalog()}
    for r in inter:
        if r["customer_id"] not in cs:
            continue
        cid = f"c:{r['customer_id']}"
        node(cid, "customer", r["customer_id"][-6:], segment=r["segment"])
        if r["product_id"]:
            node(f"p:{r['product_id']}", "product", names.get(r["product_id"], r["product_id"]))
            edges.append({"source": cid, "target": f"p:{r['product_id']}", "relation": "interested_in"})
    for n in c.execute("SELECT customer_id, objections FROM intel"):
        if n["customer_id"] in cs:
            for o in json.loads(n["objections"] or "[]"):
                node(f"o:{o}", "objection", o)
                edges.append({"source": f"c:{n['customer_id']}", "target": f"o:{o}", "relation": "raised"})
    for p in c.execute("SELECT * FROM payments"):
        if p["customer_id"] in cs:
            pid = f"pay:{p['intent_id']}"
            node(pid, "payment", f"{int(p['amount'] or 0)} TND", status=p["status"])
            edges.append({"source": f"c:{p['customer_id']}", "target": pid, "relation": "paid"})
            if p["product_id"]:
                node(f"p:{p['product_id']}", "product", names.get(p["product_id"], p["product_id"]))
                edges.append({"source": pid, "target": f"p:{p['product_id']}", "relation": "for"})
    for al in c.execute("SELECT * FROM alerts ORDER BY ts DESC LIMIT 60"):
        aid = f"a:{al['alert_id']}"
        if al["customer_id"] and al["customer_id"] in cs:
            node(aid, "alert", al["type"], severity=al["severity"])
            edges.append({"source": aid, "target": f"c:{al['customer_id']}", "relation": "flagged"})
    # dedupe edges
    seen, uniq = set(), []
    for e in edges:
        k = (e["source"], e["target"], e["relation"])
        if k not in seen and e["source"] in nodes and e["target"] in nodes:
            seen.add(k); uniq.append(e)
    return {"nodes": list(nodes.values()), "edges": uniq}


def refused_count(c: sqlite3.Connection, customer_id: str) -> int:
    return c.execute("SELECT COUNT(*) FROM payments WHERE customer_id=? AND status='refused'", (customer_id,)).fetchone()[0]
