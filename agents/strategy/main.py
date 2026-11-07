"""Business Strategy Agent. PHASE 0 STUB written by A, owned by B after CP0.

Turns KPIs into data backed recommendations that a human approves.
"""
from __future__ import annotations

from common.a2a import call, create_agent_app
from common.events import emit
from common.schemas import Recommendation

RECS: dict[str, dict] = {}


def build(k: dict) -> list[Recommendation]:
    recs = []
    total = max(1, k["interactions_total"])
    objs = {o["label"]: o["count"] for o in k["top_objections"]}
    n_obj = max(1, sum(objs.values()))
    price = objs.get("price", 0)
    if price:
        recs.append(Recommendation(
            title="Offer 3 installments by default on price objections",
            rationale=f"Price is {round(100 * price / n_obj)}% of all objections ({price} of {n_obj}).",
            evidence={"price_objections": price, "objections_total": n_obj, "conversion_rate": k["conversion_rate"]},
            expected_impact="+3 to +5 points of conversion on hesitant leads"))
    ch = k.get("by_channel", {})
    if ch:
        best = max(ch, key=ch.get)
        recs.append(Recommendation(
            title=f"Push the {best} channel in campaigns",
            rationale=f"{ch[best]} of {total} interactions come from {best}.",
            evidence={"by_channel": ch}, expected_impact="lower cost per lead"))
    abuse = k["alerts_by_type"].get("discount_abuse", 0) + k["alerts_by_type"].get("prompt_injection", 0)
    if abuse:
        recs.append(Recommendation(
            title="Keep the discount cap and add the approved vaccines to the sales script",
            rationale=f"{abuse} manipulation attempts detected (discount abuse or injection).",
            evidence={"alerts_by_type": k["alerts_by_type"]}, expected_impact="protects margin, zero unauthorized discounts"))
    if k.get("avg_satisfaction") and k["avg_satisfaction"] < 3.8:
        recs.append(Recommendation(
            title="Add a free trial session before payment",
            rationale=f"Average satisfaction is {k['avg_satisfaction']}/5.",
            evidence={"avg_satisfaction": k["avg_satisfaction"]}, expected_impact="builds trust before purchase"))
    return recs[:3]


async def recommend(data: dict, ctx: dict) -> dict:
    """Read the KPIs and produce up to 3 data backed recommendations."""
    k = await call("analyst", "kpis", {"filters": data.get("filters") or {}})
    recs = [r.model_dump() for r in build(k)]
    for r in recs:
        RECS[r["rec_id"]] = r
    await emit("strategy.recommendation", {"items": recs})
    return {"items": recs}


async def decide(data: dict, ctx: dict) -> dict:
    """Approve or reject a recommendation (human decision from the dashboard)."""
    r = RECS.get(data.get("rec_id", ""))
    if not r:
        return {"error": "unknown recommendation"}
    r["status"] = "approved" if data.get("decision") == "approve" else "rejected"
    await emit("strategy.recommendation", {"items": [r]})
    return r


async def list_recs(data: dict, ctx: dict) -> dict:
    """List recommendations produced in this session."""
    return {"items": list(RECS.values())[-10:]}


app = create_agent_app("strategy", "Business Strategy: data backed recommendations for offer, script and pricing", {
    "recommend": recommend, "decide": decide, "list": list_recs})
