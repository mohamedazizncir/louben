"""Red Team agent: live campaign wiring, with the network replaced by fakes."""
import asyncio

import pytest

import agents.redteam.main as redteam
from agents.security.guards import check_input
from common.a2a import A2AError


@pytest.fixture
def rt(keys, events, monkeypatch):
    monkeypatch.setattr(redteam, "emit", events)
    redteam.LAST.update(score=None, results=[])
    state = {"rules": [], "approved": [], "chat_calls": 0, "down": set()}

    async def fake_call(target, skill, data=None, **kw):
        if target in state["down"]:
            raise A2AError(f"{target} unreachable", state="error")
        if (target, skill) == ("sales", "chat"):
            state["chat_calls"] += 1
            ok = check_input(data["text"], extra_rules=state["approved"]).allowed
            return {"stage": "discovery" if ok else "blocked", "reply": "..."}
        if (target, skill) == ("intel", "analyze"):
            text = " ".join(t["text"] for t in data["turns"])
            return {"injection_flagged": not check_input(text).allowed}
        if (target, skill) == ("security", "propose_rule"):
            state["rules"].append(data)
            return {**data, "status": "proposed"}
        raise AssertionError((target, skill))

    async def fake_raw_rpc(target, skill, data, token):
        return {"error": {"code": -32001, "message": "unauthorized"}}

    monkeypatch.setattr(redteam, "call", fake_call)
    monkeypatch.setattr(redteam, "raw_rpc", fake_raw_rpc)
    monkeypatch.setattr(redteam, "approved_rules", lambda: state["approved"])
    return state


def run(coro):
    return asyncio.run(coro)


def test_first_campaign_lets_the_novel_attack_through_and_proposes_a_vaccine(rt, events):
    out = run(redteam.run_campaign({"attacks": "all"}, {"caller": "hub"}))
    assert len(out["results"]) == 12
    passed = [r["name"] for r in out["results"] if not r["blocked"]]
    assert passed == ["novel_owner_claim"]
    assert out["immunity_score"] == 92  # percent, as the dashboard gauge expects
    assert len(events.of("redteam.attack")) == 12
    assert events.of("redteam.score")[-1] == {"immunity_score": 92, "blocked": 11, "total": 12}
    assert len(rt["rules"]) == 1 and rt["rules"][0]["from_attack_id"] == "RT12"


def test_after_vaccine_approval_immunity_is_100(rt):
    run(redteam.run_campaign({}, {"caller": "hub"}))
    rt["approved"] = [{**r, "status": "approved"} for r in rt["rules"]]
    out = run(redteam.run_campaign({}, {"caller": "hub"}))
    assert out["immunity_score"] == 100
    blocked_by = {r["name"]: r["blocked_by"] for r in out["results"]}
    assert "vaccine" in blocked_by["novel_owner_claim"]


def test_selected_attacks_only(rt):
    out = run(redteam.run_campaign({"attacks": ["direct_injection", "replay"]}, {"caller": "hub"}))
    assert [r["name"] for r in out["results"]] == ["direct_injection", "replay"]


def test_unreachable_target_falls_back_to_offline_check_and_says_so(rt):
    rt["down"].add("sales")
    out = run(redteam.run_campaign({"attacks": ["direct_injection"]}, {"caller": "hub"}))
    r = out["results"][0]
    assert r["blocked"] and "offline" in r["blocked_by"]


def test_score_returns_last_campaign(rt):
    run(redteam.run_campaign({}, {"caller": "hub"}))
    s = run(redteam.score({}, {"caller": "hub"}))
    assert s["immunity_score"] == 92 and len(s["results"]) == 12


def test_score_after_restart_comes_from_history(rt, monkeypatch):
    async def history():
        return {"immunity_score": 83, "blocked": 10, "total": 12}
    monkeypatch.setattr(redteam, "last_score_from_history", history)
    s = run(redteam.score({}, {"caller": "hub"}))
    assert s["immunity_score"] == 83 and s["blocked"] == 10 and s["total"] == 12
    assert s["from_history"] is True


def test_score_includes_blocked_and_total_after_campaign(rt):
    run(redteam.run_campaign({}, {"caller": "hub"}))
    s = run(redteam.score({}, {"caller": "hub"}))
    assert s["blocked"] == 11 and s["total"] == 12 and s["from_history"] is False
