"""Business Strategy Agent. Owner: B.

Reads analyst.kpis + recent intel.report events, produces 3 recommendations
backed by numbers (agents/strategy/rules.py), one of them security aware.
The LLM may rephrase a recommendation but never change its numbers. Every
recommendation stays `proposed` until a human approves it on the dashboard.
"""
from __future__ import annotations

import httpx

from agents.strategy import rules
from common import config, llm
from common.a2a import A2AError, SkillRejected, call, create_agent_app
from common.events import emit

RECS: dict[str, dict] = {}


async def _intel_reports(limit: int = 200) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            r = await c.get(f"{config.url('hub')}/api/events", params={"type": "intel.report", "limit": limit})
        return [e["data"] for e in r.json().get("items", [])]
    except Exception:
        return []


async def _polish(rec: dict) -> dict:
    """Optional LLM rephrasing. Rejected if it introduces a number not in the evidence."""
    if not llm.available():
        return rec
    out = await llm.chat_json([
        {"role": "system", "content": "Rewrite this business recommendation for a sales manager. Keep it short. "
         "Use ONLY numbers that appear in the evidence. Answer JSON: {\"title\": str, \"rationale\": str}."},
        {"role": "user", "content": f"title: {rec['title']}\nrationale: {rec['rationale']}\nevidence: {rec['evidence']}"}],
        fallback={}, max_tokens=160)
    title, rationale = str(out.get("title", "")).strip(), str(out.get("rationale", "")).strip()
    if title and rationale and rules.numbers_grounded(title + " " + rationale, rec["evidence"]):
        return {**rec, "title": title[:140], "rationale": rationale[:400]}
    return rec


async def recommend(data: dict, ctx: dict) -> dict:
    """Read the KPIs and recent intel reports, produce 3 data backed recommendations (one security aware)."""
    try:
        k = await call("analyst", "kpis", {"filters": data.get("filters") or {}})
    except A2AError:
        k = {}
    recs = [await _polish(r) for r in rules.build(k, await _intel_reports(), config.load_json("policy.json"))]
    for r in recs:
        RECS[r["rec_id"]] = r
    await emit("strategy.recommendation", {"items": recs})
    return {"items": recs}


async def decide(data: dict, ctx: dict) -> dict:
    """Approve or reject a recommendation (human decision from the dashboard)."""
    r = RECS.get(data.get("rec_id", ""))
    if not r:
        raise SkillRejected("unknown recommendation")
    r["status"] = "approved" if data.get("decision") == "approve" else "rejected"
    await emit("strategy.recommendation", {"items": [r]})
    return r


async def list_recs(data: dict, ctx: dict) -> dict:
    """List recommendations produced in this session."""
    return {"items": list(RECS.values())[-10:]}


app = create_agent_app("strategy", "Business Strategy: data backed recommendations for offer, script and pricing", {
    "recommend": recommend, "decide": decide, "list": list_recs})
