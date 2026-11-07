"""Financial Data Analyst Agent: KPIs, drill downs, knowledge graph, forecast, multisig co-signer. Owner: A."""
from __future__ import annotations

import asyncio

from agents.analyst import store
from common import config, crypto
from common.a2a import create_agent_app
from common.schemas import PaymentIntent, Signature

DB = store.connect()
_lock = asyncio.Lock()


async def ingest(data: dict, ctx: dict) -> dict:
    """Store a platform event (interactions, intel, payments, alerts, recommendations)."""
    async with _lock:
        ok = store.ingest(DB, data)
    return {"ok": ok}


async def kpis(data: dict, ctx: dict) -> dict:
    """Return every dashboard KPI, optionally filtered (from, to, segment, product_id, channel)."""
    return store.kpis(DB, data.get("filters") or {})


async def drilldown(data: dict, ctx: dict) -> dict:
    """Return the rows behind a KPI (example kpi: 'payments:refused', 'objections:price')."""
    return store.drilldown(DB, data.get("kpi", "interactions"), data.get("filters") or {})


async def knowledge(data: dict, ctx: dict) -> dict:
    """Return the knowledge graph (customers, products, objections, payments, alerts)."""
    return store.knowledge(DB, data.get("filters") or {})


def signing_payload(sig: Signature) -> dict:
    return {"intent_id": sig.intent_id, "intent_hash": sig.intent_hash, "signer": sig.signer, "decision": sig.decision}


async def sign(data: dict, ctx: dict) -> dict:
    """Co-sign a payment intent if the discount respects the company policy and the customer history is clean."""
    intent = PaymentIntent(**data)
    policy = config.load_json("policy.json")
    seg = intent.segment or "individual"
    max_disc = float(policy.get("max_discount_pct", {}).get(seg, 10))
    refused = store.refused_count(DB, intent.customer_id)
    if intent.discount_pct > max_disc:
        decision, reason = "refuse", f"discount {intent.discount_pct}% above policy max {max_disc}% for {seg}"
    elif intent.installments not in policy.get("installments_allowed", [1, 2, 3]):
        decision, reason = "refuse", f"{intent.installments} installments not allowed"
    elif refused >= 2:
        decision, reason = "refuse", f"customer has {refused} refused payments"
    else:
        decision, reason = "approve", f"discount {intent.discount_pct}% within policy ({max_disc}% max for {seg})"
    sig = Signature(intent_id=intent.intent_id, intent_hash=intent.intent_hash, signer="analyst",
                    decision=decision, reason=reason)
    sig.signature_b64 = crypto.sign_obj("analyst", signing_payload(sig))
    return sig.model_dump()


app = create_agent_app("analyst", "Financial Data Analyst: KPIs, revenue, conversion, forecast, policy co-signer", {
    "ingest": ingest, "kpis": kpis, "drilldown": drilldown, "knowledge": knowledge, "sign": sign})
