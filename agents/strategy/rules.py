"""Strategy rules: KPIs + intel reports -> 3 data backed recommendations. Pure functions.

Every recommendation carries the numbers it is based on (`evidence`). Two are
business recommendations (highest impact first), one is always security aware.
An LLM may rephrase them, but `numbers_grounded` rejects any rephrasing that
contains a number not present in the evidence (no invented statistics).
"""
from __future__ import annotations

import json
import re
from collections import Counter

from common.schemas import Recommendation

REDTEAM_PREFIX = "redteam-"
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _pct(part: float, total: float) -> int:
    return round(100 * part / total) if total else 0


def summarize_reports(reports: list[dict]) -> dict:
    """Recent intel reports from real customers (red team traffic excluded)."""
    real = [r for r in reports if not str(r.get("customer_id", "")).startswith(REDTEAM_PREFIX)]
    return {"count": len(real),
            "objections": dict(Counter(o for r in real for o in r.get("objections", []))),
            "needs": dict(Counter(n for r in real for n in r.get("needs", [])).most_common(3))}


def _rec(title: str, rationale: str, evidence: dict, impact: str) -> dict:
    return Recommendation(title=title, rationale=rationale, evidence=evidence, expected_impact=impact).model_dump()


def _business(k: dict, recent: dict) -> list[tuple[float, dict]]:
    out = []
    objs = {o["label"]: o["count"] for o in k.get("top_objections", [])}
    total_obj = sum(objs.values())
    price = objs.get("price", 0)
    if price and total_obj:
        share = _pct(price, total_obj)
        ev = {"kind": "price_objection", "price_objections": price, "objections_total": total_obj,
              "share_pct": share, "conversion_rate_pct": round(100 * float(k.get("conversion_rate", 0)), 1),
              "installments": 3}
        if recent.get("count"):
            ev["recent_conversations"] = recent["count"]
        out.append((share, _rec(
            "Offer 3 installments by default when price comes up",
            f"Price is {share}% of {total_obj} objections ({price} conversations).",
            ev, "+3 to +5 points of conversion on hesitant leads")))

    avg = k.get("avg_satisfaction")
    dist = k.get("satisfaction_dist") or {}
    if avg and avg < 3.8:
        n = sum(dist.values())
        low = dist.get("1", 0) + dist.get("2", 0)
        out.append(((3.8 - avg) * 40, _rec(
            "Add a free trial session before payment",
            f"Average satisfaction is {avg}/5; {_pct(low, n)}% of {n} ratings are 1 or 2 stars.",
            {"kind": "satisfaction", "avg_satisfaction": avg, "low_ratings": low, "ratings_total": n,
             "low_share_pct": _pct(low, n)}, "builds trust before purchase, fewer refunds")))

    pay = k.get("payments") or {}
    n_pay = sum(pay.values())
    refused = pay.get("refused", 0)
    if n_pay and _pct(refused, n_pay) >= 10:
        share = _pct(refused, n_pay)
        out.append((share * 1.5, _rec(
            "After a refused card, propose 2 or 3 installments instead of a plain retry",
            f"{refused} of {n_pay} payments were refused ({share}%).",
            {"kind": "payment_refusal", "refused": refused, "payments_total": n_pay, "refused_share_pct": share,
             "installments": 3}, "recovers part of the refused revenue")))

    rev = k.get("revenue_by_product") or {}
    total_rev = sum(rev.values())
    if rev and total_rev:
        top = max(rev, key=rev.get)
        share = _pct(rev[top], total_rev)
        if share >= 25:
            out.append((share * 0.8, _rec(
                f"Run a dedicated B2B campaign for {top}",
                f"{top} brings {share}% of the {round(total_rev)} TND simulated revenue.",
                {"kind": "revenue_concentration", "product_id": top, "product_revenue": rev[top],
                 "revenue_total": round(total_rev), "share_pct": share}, "grows the highest value offer")))
    return out


def _security(k: dict, policy: dict) -> dict:
    alerts = k.get("alerts_by_type") or {}
    inj, abuse = alerts.get("prompt_injection", 0), alerts.get("discount_abuse", 0)
    caps = policy.get("max_discount_pct", {})
    cap = caps.get("individual", caps.get("default", 10)) if isinstance(caps, dict) else caps
    human_pct = policy.get("human_discount_pct", 10)
    ev = {"security": True, "prompt_injection": inj, "discount_abuse": abuse, "attempts": inj + abuse,
          "max_discount_pct": cap, "human_discount_pct": human_pct}
    if inj + abuse:
        return _rec(f"Keep the discount cap at {cap}% for individual customers, human key above {human_pct}%",
                    f"{inj + abuse} manipulation attempts detected ({inj} prompt injection, {abuse} discount abuse).",
                    ev, "protects margin: zero unauthorized discounts")
    return _rec("Keep running the Red Team campaign every week",
                "No manipulation attempt recorded yet; new phrasings appear over time.",
                ev, "new attack phrasings get a vaccine before real customers use them")


def build(kpis: dict, reports: list[dict], policy: dict) -> list[dict]:
    recent = summarize_reports(reports)
    business = [r for _, r in sorted(_business(kpis, recent), key=lambda x: -x[0])][:2]
    return business + [_security(kpis, policy)]


def _numbers(obj) -> set[float]:
    return {float(n.replace(",", ".")) for n in _NUM.findall(json.dumps(obj))}


def numbers_grounded(text: str, evidence: dict) -> bool:
    allowed = _numbers(evidence)
    return all(float(n.replace(",", ".")) in allowed for n in _NUM.findall(text or ""))
