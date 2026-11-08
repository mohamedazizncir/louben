import random
from datetime import datetime, timezone

from data.seed_trust import build

NOW = datetime(2026, 11, 8, 2, 0, tzinfo=timezone.utc)


def events():
    return build(NOW, random.Random(1))


def test_has_alerts_of_every_schema_type():
    types = {e["data"]["type"] for e in events() if e["type"] == "security.alert"}
    assert types == {"prompt_injection", "discount_abuse", "velocity", "amount_mismatch", "spoofed_agent",
                     "scope_violation", "replay", "tampering", "exfiltration", "fake_approval"}


def test_events_are_in_the_past_and_sorted():
    evs = events()
    assert [e["ts"] for e in evs] == sorted(e["ts"] for e in evs)
    assert all(e["ts"] <= NOW.isoformat() for e in evs)


def test_payments_carry_analyst_fields_and_only_fake_tokens():
    pays = [e["data"] for e in events() if e["type"] == "payment.status"]
    assert pays
    for p in pays:
        assert {"intent_id", "status", "amount", "customer_id", "product_id", "segment"} <= set(p)
        assert p["payment_token_kind"].startswith("tok_")


def test_risky_payments_have_a_human_key():
    evs = events()
    for ap in (e["data"] for e in evs if e["type"] == "gate.approved"):
        signers = {e["data"]["signer"] for e in evs if e["type"] == "gate.signature"
                   and e["data"]["intent_id"] == ap["intent_id"]}
        assert {"payment", "security", "analyst"} <= signers
        if ap["amount"] > 1000:
            assert "human" in signers


def test_seed_chain_verifies(tmp_path, monkeypatch):
    from common import audit
    monkeypatch.setattr(audit, "DB", tmp_path / "audit.db")
    for ev in events():
        audit.append(ev)
    assert audit.verify()["ok"]
