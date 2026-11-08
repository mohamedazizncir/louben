"""Synthetic business history (30 days) so the dashboard is alive from the start.

All data is FAKE. Usage: python -m data.seed
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.analyst import store  # noqa: E402
from common import config  # noqa: E402

FIRST = ["Amine", "Yasmine", "Skander", "Mariem", "Youssef", "Ines", "Hamza", "Salma", "Omar", "Rania", "Aziz",
         "Nour", "Firas", "Eya", "Karim", "Lina", "Mehdi", "Sarra", "Bilel", "Asma"]
LAST = ["B.", "K.", "M.", "T.", "H.", "S.", "J.", "D.", "Z.", "N."]
SEGMENTS = [("student", 0.45), ("professional", 0.30), ("individual", 0.17), ("company", 0.08)]
OBJ = [("price", 0.42), ("time", 0.2), ("level", 0.14), ("trust", 0.12), ("payment", 0.12)]
PRODUCT_W = {"ai-fundamentals": 0.24, "genai-agents": 0.2, "data-analytics": 0.14, "fullstack-web": 0.12,
             "ml-bootcamp": 0.08, "pfe-supervision": 0.12, "summer-internship": 0.07, "corporate-ai-pack": 0.03}


def pick(weighted):
    r, acc = random.random(), 0.0
    for v, w in weighted:
        acc += w
        if r <= acc:
            return v
    return weighted[-1][0]


def main(days: int = 30, n: int = 320, seed: int = 7) -> None:
    random.seed(seed)
    path = store.DB_PATH
    try:
        path.unlink(missing_ok=True)
    except PermissionError:                      # Windows: file held open by a running analyst
        pass
    c = store.connect(path)
    for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        c.execute(f"DELETE FROM {table}")
    prods = {p["product_id"]: p for p in config.catalog()}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for i in range(n):
        day = days - 1 - int((random.random() ** 0.8) * days)          # more recent activity
        ts = now - timedelta(days=day, hours=random.randint(0, 10), minutes=random.randint(0, 59))
        seg = pick(SEGMENTS)
        cid = f"cust-{i:04d}"
        pid = pick(list(PRODUCT_W.items())) if seg != "company" or random.random() < 0.5 else "corporate-ai-pack"
        channel = "voice" if random.random() < 0.38 else "text"
        objs = sorted({pick(OBJ) for _ in range(random.choice([0, 1, 1, 2]))})
        trend = 1 + (days - day) / days * 0.6                              # conversion improves over time
        p_buy = 0.11 * trend * (0.7 if "price" in objs else 1.1) * (1.15 if channel == "voice" else 1)
        bought = random.random() < p_buy
        interested = bought or random.random() < 0.38
        outcome = "purchase_started" if bought else ("interested" if interested else random.choice(["not_interested", "open"]))
        sent = round(random.uniform(0.1, 0.9) if interested else random.uniform(-0.7, 0.3), 2)
        sat = max(1, min(5, round(3 + sent * 1.6 + random.uniform(-0.6, 0.6))))
        name = f"{random.choice(FIRST)} {random.choice(LAST)}"
        c.execute("INSERT OR IGNORE INTO customers VALUES(?,?,?)", (cid, name, seg))
        iid = f"int-seed{i:04d}"
        c.execute("INSERT INTO interactions VALUES(?,?,?,?,?,?,?,?,?,?)", (
            iid, cid, channel, pid, outcome, seg, ts.isoformat(), (ts + timedelta(minutes=4)).isoformat(),
            random.randint(4, 12), "[]"))
        c.execute("INSERT INTO intel VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            iid, cid, json.dumps(["ai"]), json.dumps(objs), json.dumps(["career"]), sent,
            round(random.uniform(0.6, 0.95) if interested else random.uniform(0.05, 0.4), 2), sat, seg,
            round(random.uniform(0.0, 0.5) if interested else random.uniform(0.4, 0.9), 2), ts.isoformat()))
        if bought or (interested and random.random() < 0.18):
            disc = random.choice([0, 0, 0, 5, 10, 10, 15 if seg == "student" else 10])
            amount = round(prods[pid]["list_price"] * (1 - disc / 100), 2)
            status = "succeeded" if bought else random.choice(["refused", "refused", "pending"])
            c.execute("INSERT INTO payments VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                f"pi-seed{i:04d}", cid, pid, amount, disc, random.choice([1, 1, 3]), status,
                "simulated", seg, channel, (ts + timedelta(minutes=5)).isoformat()))
    alert_types = [("prompt_injection", "high"), ("discount_abuse", "medium"), ("velocity", "high"),
                   ("scope_violation", "high"), ("spoofed_agent", "critical")]
    for j in range(18):
        t, sev = random.choice(alert_types)
        ts = now - timedelta(days=random.randint(0, days - 1), hours=random.randint(0, 20))
        c.execute("INSERT INTO alerts VALUES(?,?,?,?,?,?,?)", (
            f"al-seed{j:03d}", t, sev, "security", f"cust-{random.randint(0, n - 1):04d}", "{}", ts.isoformat()))
    c.commit()
    k = store.kpis(c)
    print(f"[seed] {k['interactions_total']} interactions, conversion {k['conversion_rate']:.1%}, "
          f"revenue {k['revenue_simulated']} TND, {k['alerts_total']} alerts -> {path}")


if __name__ == "__main__":
    main()
