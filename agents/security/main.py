"""Security & Fraud Agent. PHASE 0 STUB written by A, owned by B after CP0.

Works already (simple rules) so the demo runs end to end. B replaces with guards.py / fraud.py / offers.py.
"""
from __future__ import annotations

import base64
import json
import re
import time
import unicodedata
from collections import defaultdict, deque

from common import config, crypto
from common.a2a import create_agent_app
from common.events import emit
from common.schemas import InputCheck, OfferCheck, PaymentIntent, ProposedRule, Signature

RULES_FILE = config.DATA_DIR / "rules.json"

PATTERNS = [
    ("prompt_injection", r"ignore (all |your |the )?(previous |prior )?(instructions|rules)"),
    ("prompt_injection", r"oublie (tes|les|toutes les) (regles|instructions)"),
    ("prompt_injection", r"(system prompt|developer mode|you are now|tu es maintenant|jailbreak|dan mode)"),
    ("prompt_injection", r"(nsa|ensa) (el|les)? ?(9wa3ed|qawa3ed|regles)"),
    ("discount_abuse", r"(manager|directeur|boss|patron|admin)\b.{0,40}(approved|approuve|accepte|valide|autorise)"),
    ("discount_abuse", r"\b(100|9\d|[5-8]\d)\s*(%|pour ?cent|percent)"),
    ("discount_abuse", r"(gratuit|for free|free of charge|bla flous|b'blech|bel bleech)"),
    ("exfiltration", r"(other|autres?|all|tous les) (customers?|clients?).{0,40}(email|mail|phone|card|carte|data|donnees)"),
    ("exfiltration", r"(api key|password|mot de passe|private key|cle privee|secret|card number|numero de carte)"),
]

_recent_intents: dict[str, deque] = defaultdict(deque)
_customer_alerts: dict[str, int] = defaultdict(int)


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.translate(str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a"}))


def load_rules() -> list[dict]:
    try:
        return json.loads(RULES_FILE.read_text())
    except Exception:
        return []


def save_rules(rules: list[dict]) -> None:
    RULES_FILE.write_text(json.dumps(rules, indent=2))


def scan(text: str) -> list[tuple[str, str]]:
    t = norm(text)
    hits = [(cat, pat) for cat, pat in PATTERNS if re.search(pat, t)]
    for r in load_rules():
        if r.get("status") == "approved":
            try:
                if re.search(r["pattern"], t):
                    hits.append(("prompt_injection", f"vaccine:{r['rule_id']}"))
            except re.error:
                pass
    return hits


async def check_input(data: dict, ctx: dict) -> dict:
    """Detect prompt injection, fake authority, discount abuse and data exfiltration in untrusted text."""
    text = data.get("text", "") or ""
    hits = scan(text)
    risk = min(1.0, 0.5 * len(hits))
    res = InputCheck(allowed=not hits, risk_score=risk, reasons=[f"{c}: {p}" for c, p in hits], sanitized_text=text[:500])
    await emit("input.checked", {"context": data.get("context"), "allowed": res.allowed, "risk_score": risk,
                                 "caller": ctx["caller"]}, severity="info" if res.allowed else "warning")
    if hits:
        cid = data.get("customer_id")
        if cid:
            _customer_alerts[cid] += 1
        await emit("security.alert", {"type": hits[0][0], "severity": "high", "customer_id": cid,
                                      "requires_human": False,
                                      "details": {"excerpt": text[:120], "reasons": res.reasons, "context": data.get("context")}},
                   severity="warning")
    return res.model_dump()


async def check_offer(data: dict, ctx: dict) -> dict:
    """Discount guardrail: an offer is allowed only within the signed company policy."""
    offer = data.get("offer") or {}
    seg = data.get("segment") or "individual"
    policy = config.load_json("policy.json")
    max_d = float(policy["max_discount_pct"].get(seg, 10))
    disc = float(offer.get("discount_pct", 0))
    inst_ok = int(offer.get("installments", 1)) in policy.get("installments_allowed", [1, 2, 3])
    p = config.product(offer.get("product_id", ""))
    price_ok = bool(p) and abs(p["list_price"] * (1 - disc / 100) - float(offer.get("final_price", -1))) < 0.05
    allowed = disc <= max_d and inst_ok and price_ok
    reason = "within policy" if allowed else (f"discount {disc}% > max {max_d}% for {seg}" if disc > max_d else
                                              "price or installments not consistent with catalog")
    res = OfferCheck(allowed=allowed, max_discount_pct=max_d, reason=reason)
    await emit("offer.checked", {**res.model_dump(), "requested_pct": disc, "segment": seg,
                                 "customer_id": data.get("customer_id")}, severity="info" if allowed else "warning")
    if disc > max_d:
        await emit("security.alert", {"type": "discount_abuse", "severity": "medium", "customer_id": data.get("customer_id"),
                                      "details": {"requested_pct": disc, "max_pct": max_d}}, severity="warning")
    return res.model_dump()


async def sign(data: dict, ctx: dict) -> dict:
    """Fraud checks (velocity, anomaly, customer alerts) then co-sign or refuse the intent."""
    intent = PaymentIntent(**data)
    policy = config.load_json("policy.json")
    q, now = _recent_intents[intent.customer_id], time.time()
    q.append(now)
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) > int(policy.get("velocity_max_intents_per_minute", 3)):
        decision, reason, alert = "refuse", f"velocity: {len(q)} intents in 60s", "velocity"
    elif _customer_alerts[intent.customer_id] >= 2:
        decision, reason, alert = "refuse", "customer has recent security alerts", "prompt_injection"
    elif intent.amount > 10000:
        decision, reason, alert = "refuse", "amount anomaly", "amount_mismatch"
    else:
        decision, reason, alert = "approve", "no fraud signal", None
    sig = Signature(intent_id=intent.intent_id, intent_hash=intent.intent_hash, signer="security",
                    decision=decision, reason=reason)
    sig.signature_b64 = crypto.sign_obj("security", {"intent_id": sig.intent_id, "intent_hash": sig.intent_hash,
                                                     "signer": "security", "decision": decision})
    if alert:
        await emit("security.alert", {"type": alert, "severity": "high", "customer_id": intent.customer_id,
                                      "details": {"intent_id": intent.intent_id, "reason": reason}}, severity="warning")
    return sig.model_dump()


async def list_rules(data: dict, ctx: dict) -> dict:
    """List proposed and approved security rules (vaccines)."""
    return {"items": load_rules()}


async def propose_rule(data: dict, ctx: dict) -> dict:
    """Store a rule proposed by the red team (needs human approval)."""
    rule = ProposedRule(**data)
    rules = load_rules()
    if not any(r["pattern"] == rule.pattern for r in rules):
        rules.append(rule.model_dump())
        save_rules(rules)
        await emit("rule.proposed", rule.model_dump(), severity="warning")
    return rule.model_dump()


async def rule_decision(data: dict, ctx: dict) -> dict:
    """Approve or reject a proposed rule (called by the hub after human login)."""
    rules = load_rules()
    for r in rules:
        if r["rule_id"] == data.get("rule_id"):
            r["status"] = "approved" if data.get("decision") == "approve" else "rejected"
            save_rules(rules)
            if r["status"] == "approved":
                await emit("rule.approved", r)
            return r
    return {"error": "unknown rule"}


app = create_agent_app("security", "Security & Fraud: input guard, discount guardrails, fraud rules, co-signer", {
    "check_input": check_input, "check_offer": check_offer, "sign": sign,
    "list_rules": list_rules, "propose_rule": propose_rule, "rule_decision": rule_decision})
