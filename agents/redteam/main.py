"""Red Team Agent.

Runs the attack library (agents/redteam/attacks.py) against the LIVE platform
through real A2A calls, so every attack shows on the agent graph. If a target
is unreachable, the attack is replayed offline against the same pure trust
code and the result says "(offline)" - the score is never faked.

Attacks that get through produce a vaccine (ProposedRule) sent to Security;
it only applies after a human approves it on the dashboard.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx

from agents.redteam import attacks as lib
from agents.security.guards import check_input
from common import config, crypto, llm
from common.a2a import A2AError, call, create_agent_app
from common.events import emit

LAST: dict = {"score": None, "results": []}
RULES_FILE = config.DATA_DIR / "rules.json"


def approved_rules() -> list[dict]:
    try:
        return [r for r in json.loads(RULES_FILE.read_text(encoding="utf-8")) if r.get("status") == "approved"]
    except Exception:
        return []


async def raw_rpc(target: str, skill: str, data: dict, token: str) -> dict:
    """Send a JSON-RPC call with an arbitrary token (used to test auth defenses)."""
    payload = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send",
               "params": {"skill": skill, "message": {"role": "agent", "parts": [{"kind": "data", "data": data}]}}}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{config.url(target)}/", json=payload, headers={"Authorization": f"Bearer {token}"})
        return r.json()


def _refused(r: dict) -> bool:
    return "error" in r or (r.get("result", {}).get("status", {}).get("state") in ("rejected", "failed"))


# ---------------------------------------------------------------- live executors
async def _chat(attack: lib.Attack) -> tuple[bool, str]:
    sid = f"rt-{uuid.uuid4().hex[:8]}"
    r = await call("sales", "chat", {"session_id": sid, "customer_id": f"redteam-{sid}", "text": attack.payload,
                                     "channel": "text"})
    if r.get("stage") == "blocked":
        # built-in rules alone would let it through -> an approved vaccine blocked it
        return True, "security.check_input" if not check_input(attack.payload).allowed else "security.vaccine"
    return False, ""


async def _indirect(attack: lib.Attack) -> tuple[bool, str]:
    it = {"customer_id": f"redteam-{uuid.uuid4().hex[:6]}", "channel": "text",
          "turns": [{"role": "customer", "text": attack.payload}], "outcome": "open"}
    r = await call("intel", "analyze", it)
    if "injection_flagged" in r:
        return bool(r["injection_flagged"]), "intel -> security.check_input"
    blocked = not check_input(attack.payload, extra_rules=approved_rules()).allowed
    return blocked, "security.check_input (local check of intel transcript)"


async def _auth(target: str, skill: str, data: dict, token: str, layer: str, attack: lib.Attack) -> tuple[bool, str]:
    live = _refused(await raw_rpc(target, skill, data, token))
    deep = lib.run_local(attack)["blocked"]  # the deeper layer behind the network check
    return live, f"{layer}; {attack.expected_layer} (offline check: {'blocked' if deep else 'PASSED'})"


async def _spoof(a):
    return await _auth("gate", "submit", {"intent_id": "pi-spoof", "customer_id": "x", "product_id": "ai-fundamentals",
                                          "amount": 1}, crypto.sign_jwt("rogue", "gate", ["gate:submit"]),
                       "a2a: issuer not in key registry", a)


async def _scope(a):
    return await _auth("payment", "execute", {"intent_id": "pi-fake", "gate_proof": "forged"},
                       crypto.sign_jwt("redteam", "payment", ["payment:execute"]), "a2a: least privilege ACL", a)


async def _replay(a):
    token = crypto.sign_jwt("redteam", "security", ["security:check_input"])
    await raw_rpc("security", "check_input", {"text": "hello", "context": "redteam"}, token)
    return await _auth("security", "check_input", {"text": "hello", "context": "redteam"}, token,
                       "a2a: single use JWT (jti)", a)


async def _tamper(a):
    return await _auth("gate", "submit", {"intent_id": "pi-tamper", "amount": 1.0},
                       crypto.sign_jwt("redteam", "gate", ["gate:submit"]), "a2a: ACL", a)


async def _fake_human(a):
    return await _auth("gate", "human_decision", {"intent_id": "any", "decision": "approve", "human_jwt": "forged"},
                       crypto.sign_jwt("redteam", "gate", ["gate:human_decision"]), "a2a: ACL + human JWT", a)


async def _velocity(a):
    # simulated on purpose: 6 real sandbox payments would pollute the business KPIs
    r = lib.run_local(a)
    return r["blocked"], f"{r['blocked_by']} (simulated burst)"


LIVE = {"direct_injection": _chat, "fake_authority_discount": _chat, "encoded_injection": _chat,
        "data_exfiltration": _chat, "novel_owner_claim": _chat, "indirect_injection": _indirect,
        "spoofed_agent": _spoof, "scope_escalation": _scope, "replay": _replay, "tampering": _tamper,
        "fake_human_approval": _fake_human, "velocity_fraud": _velocity}


async def _execute(attack: lib.Attack) -> dict:
    now = datetime.now(timezone.utc)
    try:
        blocked, by = await LIVE[attack.name](attack)
        return lib.make_result(attack, blocked, by, now)
    except (A2AError, httpx.HTTPError, OSError) as e:
        r = lib.run_local(attack, extra_rules=approved_rules(), now=now)
        reason = getattr(e, "message", type(e).__name__)
        r["blocked_by"] = f"{r['blocked_by']} (offline: {reason[:40]})" if r["blocked"] else None
        return r


# ---------------------------------------------------------------- vaccines
async def _llm_regex(payload: str) -> str:
    return await llm.chat([
        {"role": "system", "content": "Write ONE Python regex (no slashes, no flags, lowercase, accents removed) "
         "that matches this attack phrasing and close variants, but not normal customer questions about "
         "courses, prices, discounts or installments. Answer with the regex only."},
        {"role": "user", "content": payload[:500]}], fallback="", max_tokens=60, temperature=0)


async def _vaccinate(attack: lib.Attack, result: dict) -> None:
    pattern = await _llm_regex(attack.payload) if llm.available() else ""
    rule = lib.propose_rule(attack, llm=(lambda _p: pattern) if pattern else None)
    try:
        await call("security", "propose_rule", rule)
    except A2AError:
        pass


# ---------------------------------------------------------------- skills
async def run_campaign(data: dict, ctx: dict) -> dict:
    """Run the attack library against the live platform and compute the immunity score (percent)."""
    results = []
    for attack in lib.get_attacks(data.get("attacks") or "all"):
        res = await _execute(attack)
        results.append(res)
        await emit("redteam.attack", res, severity="info" if res["blocked"] else "critical")
        if not res["blocked"] and attack.is_text:
            await _vaccinate(attack, res)
    blocked = sum(1 for r in results if r["blocked"])
    score = round(100 * lib.immunity_score(results))
    LAST.update(score=score, results=results)
    await emit("redteam.score", {"immunity_score": score, "blocked": blocked, "total": len(results)})
    return {"results": results, "immunity_score": score}


async def last_score_from_history() -> dict | None:
    """Last redteam.score in the audit log (so the gauge is not empty after a restart)."""
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            r = await c.get(f"{config.url('hub')}/api/audit", params={"type": "redteam.score", "limit": 1})
        items = r.json().get("items", [])
        return items[0]["data"] if items else None
    except Exception:
        return None


async def score(data: dict, ctx: dict) -> dict:
    """Return the last immunity score and attack results (from history if no campaign ran since start)."""
    if LAST["score"] is None:
        h = await last_score_from_history()
        if h:
            return {"immunity_score": h.get("immunity_score"), "blocked": h.get("blocked"),
                    "total": h.get("total"), "results": [], "from_history": True}
    results = LAST["results"]
    return {"immunity_score": LAST["score"], "results": results, "blocked": sum(1 for r in results if r["blocked"]),
            "total": len(results), "from_history": False}


app = create_agent_app("redteam", "Red Team: attacks the platform and measures the immunity score", {
    "run_campaign": run_campaign, "score": score})
