"""Hub trust routes: PIN login + lockout, human key on gate decisions, rules need a human."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from common import config
from gate import multisig
from hub import routes_trust


@pytest.fixture
def api(keys, events, monkeypatch):
    crypto = keys
    monkeypatch.setattr(routes_trust, "emit", events)
    monkeypatch.setattr(config, "HUMAN_PIN", "2026")
    routes_trust._failed_logins.clear()
    calls = []
    pending = {"items": [{"intent": {"intent_id": "pi-1", "intent_hash": "h" * 64, "amount": 1200.0},
                          "signatures": [], "reason": "amount 1200 TND > 1000 TND"}]}

    async def fake_call(target, skill, data=None, **kw):
        calls.append((target, skill, data))
        if (target, skill) == ("gate", "pending"):
            return pending
        return {"status": "executed", "payment_status": "succeeded"}

    monkeypatch.setattr(routes_trust.a2a, "call", fake_call)
    app = FastAPI()
    app.include_router(routes_trust.router)
    return {"client": TestClient(app), "calls": calls, "crypto": crypto, "events": events}


def login(c, pin="2026"):
    return c.post("/api/login", json={"pin": pin})


def test_right_pin_gives_human_token_for_gate_and_security(api):
    r = login(api["client"])
    assert r.status_code == 200
    for aud in ("gate", "security"):
        claims = api["crypto"].verify_jwt(r.json()["token"], aud=aud)
        assert claims["iss"] == "human" and "human:approve" in claims["scope"]


def test_wrong_pin_is_refused_and_alerts(api):
    assert login(api["client"], "0000").status_code == 401
    assert api["events"].of("security.alert")[-1]["type"] == "fake_approval"


def test_five_wrong_pins_lock_login_even_for_right_pin(api):
    for _ in range(5):
        login(api["client"], "0000")
    assert login(api["client"]).status_code == 429


def test_gate_decision_without_token_is_refused(api):
    r = api["client"].post("/api/gate/decision", json={"intent_id": "pi-1", "decision": "approve", "token": "x.y.z"})
    assert r.status_code == 401
    assert not any(s == "human_decision" for _, s, _ in api["calls"])


def test_gate_decision_sends_valid_human_signature_on_intent_hash(api):
    token = login(api["client"]).json()["token"]
    r = api["client"].post("/api/gate/decision", json={"intent_id": "pi-1", "decision": "approve", "token": token})
    assert r.json()["status"] == "executed"
    _, _, data = next(c for c in api["calls"] if c[1] == "human_decision")
    sig = data["human_signature"]
    body = multisig.signing_payload_dict("pi-1", "h" * 64, "human", "approve")
    assert api["crypto"].verify_obj("human", body, sig["signature_b64"])
    assert data["human_jwt"] == token


def test_gate_decision_unknown_intent_is_404(api):
    token = login(api["client"]).json()["token"]
    r = api["client"].post("/api/gate/decision", json={"intent_id": "nope", "decision": "approve", "token": token})
    assert r.status_code == 404


def test_rule_decision_requires_human_login(api):
    r = api["client"].post("/api/rules/decision", json={"rule_id": "r1", "decision": "approve", "token": "bad"})
    assert r.status_code == 401
    token = login(api["client"]).json()["token"]
    r = api["client"].post("/api/rules/decision", json={"rule_id": "r1", "decision": "approve", "token": token})
    assert r.status_code == 200
