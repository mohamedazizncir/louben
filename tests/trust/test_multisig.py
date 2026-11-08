import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gate.multisig import (
    REQUIRED_SIGNERS, canonical_json, check_freshness, compute_intent_hash,
    evaluate, finalize_intent, human_requirement, make_gate_proof,
    make_signature, signing_payload, verify_gate_proof,
)

POLICY = {"human_threshold": 1000, "human_discount_pct": 10}
NOW = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)

# real Ed25519 keys: one per signer, plus a rogue key not in the "registry"
KEYS = {name: Ed25519PrivateKey.generate() for name in (*REQUIRED_SIGNERS, "human", "gate")}
ROGUE = Ed25519PrivateKey.generate()
REGISTRY = {name: k.public_key() for name, k in KEYS.items()}


def signer_fn(key):
    return lambda payload: base64.b64encode(key.sign(payload)).decode()


def verify(signer, payload, sig_b64):
    pub = REGISTRY.get(signer)
    if pub is None:
        return False
    try:
        pub.verify(base64.b64decode(sig_b64), payload)
        return True
    except Exception:
        return False


def base_intent(**kw):
    data = {"intent_id": "i-1", "customer_id": "c-1", "product_id": "p-1",
            "amount": 450.0, "discount_pct": 10, "installments": 3,
            "payment_token": "tok_visa"}
    data.update(kw)
    return finalize_intent(data, now=NOW)


def sign_all(intent, decisions=None, key_override=None):
    decisions = decisions or {}
    sigs = []
    for s in REQUIRED_SIGNERS:
        key = (key_override or {}).get(s, KEYS[s])
        sigs.append(make_signature(intent, s, decisions.get(s, "approve"), "ok",
                                   signer_fn(key), now=NOW))
    return sigs


# --- canonical hashing -------------------------------------------------------

def test_canonical_json_is_order_and_number_format_independent():
    assert canonical_json({"b": 1, "a": 2.0}) == canonical_json({"a": 2, "b": 1.0})


def test_intent_hash_is_stable_and_sha256_hex():
    i = base_intent()
    assert i["intent_hash"] == compute_intent_hash(i)
    assert len(i["intent_hash"]) == 64


def test_any_field_change_changes_hash():
    i = base_intent()
    assert compute_intent_hash({**i, "amount": 1.0}) != i["intent_hash"]
    assert compute_intent_hash({**i, "discount_pct": 90}) != i["intent_hash"]


def test_finalize_sets_nonce_and_5_minute_expiry():
    i = base_intent()
    assert len(i["nonce"]) >= 16
    created = datetime.fromisoformat(i["created_at"])
    expires = datetime.fromisoformat(i["expires_at"])
    assert expires - created == timedelta(minutes=5)


# --- freshness / replay -------------------------------------------------------

def test_fresh_intent_ok():
    ok, reason = check_freshness(base_intent(), NOW, used_nonces=set())
    assert ok, reason


def test_reused_nonce_is_replay():
    i = base_intent()
    ok, reason = check_freshness(i, NOW, used_nonces={i["nonce"]})
    assert not ok and "replay" in reason


def test_expired_intent_is_refused():
    ok, reason = check_freshness(base_intent(), NOW + timedelta(minutes=6), set())
    assert not ok and "expired" in reason


def test_expiry_too_far_in_future_is_refused():
    i = base_intent()
    i["expires_at"] = (NOW + timedelta(hours=2)).isoformat()
    i["intent_hash"] = compute_intent_hash(i)
    ok, reason = check_freshness(i, NOW, set())
    assert not ok


# --- human threshold rules ------------------------------------------------------

@pytest.mark.parametrize("amount,discount,risk,expected", [
    (450, 10, "none", False),
    (1500, 0, "none", True),     # amount > threshold
    (450, 15, "none", True),     # discount > human_discount_pct
    (450, 10, "medium", True),   # risk >= medium
    (450, 10, "low", False),
])
def test_human_requirement(amount, discount, risk, expected):
    needed, reason = human_requirement({"amount": amount, "discount_pct": discount}, POLICY, risk)
    assert needed is expected
    assert (reason is not None) is expected


# --- signature collection -------------------------------------------------------

def test_three_valid_approvals_approve_low_risk_intent():
    i = base_intent()
    ev = evaluate(i, sign_all(i), verify, POLICY, now=NOW)
    assert ev.status == "approved" and not ev.human_required and ev.problems == []


def test_missing_signature_keeps_collecting():
    i = base_intent()
    ev = evaluate(i, sign_all(i)[:2], verify, POLICY, now=NOW)
    assert ev.status == "collecting"


def test_any_refusal_rejects():
    i = base_intent()
    ev = evaluate(i, sign_all(i, {"security": "refuse"}), verify, POLICY, now=NOW)
    assert ev.status == "rejected"


def test_big_amount_waits_for_human():
    i = base_intent(amount=1500.0, discount_pct=0)
    ev = evaluate(i, sign_all(i), verify, POLICY, now=NOW)
    assert ev.status == "pending_human"
    assert ev.human_required and "1000" in ev.human_reason


def test_valid_human_approval_approves():
    i = base_intent(amount=1500.0, discount_pct=0)
    sigs = sign_all(i) + [make_signature(i, "human", "approve", "PIN ok", signer_fn(KEYS["human"]), now=NOW)]
    assert evaluate(i, sigs, verify, POLICY, now=NOW).status == "approved"


def test_human_refusal_rejects():
    i = base_intent(amount=1500.0, discount_pct=0)
    sigs = sign_all(i) + [make_signature(i, "human", "refuse", "no", signer_fn(KEYS["human"]), now=NOW)]
    assert evaluate(i, sigs, verify, POLICY, now=NOW).status == "rejected"


def test_fake_human_signature_is_rejected_as_fake_approval():
    i = base_intent(amount=1500.0, discount_pct=0)
    sigs = sign_all(i) + [make_signature(i, "human", "approve", "trust me", signer_fn(ROGUE), now=NOW)]
    ev = evaluate(i, sigs, verify, POLICY, now=NOW)
    assert ev.status == "rejected"
    assert any(p["type"] == "fake_approval" for p in ev.problems)


def test_signature_from_rogue_key_is_spoofing():
    i = base_intent()
    ev = evaluate(i, sign_all(i, key_override={"analyst": ROGUE}), verify, POLICY, now=NOW)
    assert ev.status == "rejected"
    assert any(p["type"] == "spoofed_agent" for p in ev.problems)


def test_tampering_after_signatures_is_detected():
    i = base_intent()
    sigs = sign_all(i)
    tampered = {**i, "amount": 1.0}  # attacker keeps the old intent_hash
    ev = evaluate(tampered, sigs, verify, POLICY, now=NOW)
    assert ev.status == "rejected"
    assert any(p["type"] == "tampering" for p in ev.problems)


def test_tampering_with_recomputed_hash_breaks_old_signatures():
    i = base_intent()
    sigs = sign_all(i)
    tampered = {**i, "amount": 1.0}
    tampered["intent_hash"] = compute_intent_hash(tampered)
    ev = evaluate(tampered, sigs, verify, POLICY, now=NOW)
    assert ev.status == "rejected"
    assert any(p["type"] == "tampering" for p in ev.problems)


def test_expired_intent_is_rejected_even_with_signatures():
    i = base_intent()
    ev = evaluate(i, sign_all(i), verify, POLICY, now=NOW + timedelta(minutes=10))
    assert ev.status == "rejected"
    assert any(p["type"] == "replay" for p in ev.problems)


def test_unknown_signer_is_ignored_and_reported():
    i = base_intent()
    sigs = sign_all(i) + [make_signature(i, "sales", "approve", "", signer_fn(ROGUE), now=NOW)]
    ev = evaluate(i, sigs, verify, POLICY, now=NOW)
    assert any(p["type"] == "scope_violation" for p in ev.problems)
    assert ev.status == "rejected"


def _with_security(intent, **kw):
    sigs = [s for s in sign_all(intent) if s["signer"] != "security"]
    sigs.append(make_signature(intent, "security", "approve", "1 recent alert",
                               signer_fn(KEYS["security"]), now=NOW, **kw))
    return sigs


def test_signed_medium_risk_from_security_requires_human():
    i = base_intent()
    sigs = _with_security(i, risk_level="medium")
    assert sigs[-1]["risk_level"] == "medium"
    assert evaluate(i, sigs, verify, POLICY, now=NOW).status == "pending_human"


def test_stripping_signed_risk_level_breaks_the_signature():
    i = base_intent()
    sigs = _with_security(i, risk_level="medium")
    sigs[-1] = {k: v for k, v in sigs[-1].items() if k != "risk_level"}  # attacker hides the risk
    ev = evaluate(i, sigs, verify, POLICY, now=NOW)
    assert ev.status == "rejected"
    assert any(p["type"] == "spoofed_agent" for p in ev.problems)


def test_unsigned_risk_text_in_reason_is_ignored():
    i = base_intent()
    sigs = [s for s in sign_all(i) if s["signer"] != "security"]
    sigs.append(make_signature(i, "security", "approve", "risk=low", signer_fn(KEYS["security"]), now=NOW))
    assert evaluate(i, sigs, verify, POLICY, now=NOW).status == "approved"


def test_signing_payload_matches_common_crypto_canonical_format():
    # Analyst (owned by A) signs crypto.canonical({intent_id, intent_hash, signer, decision})
    body = {"intent_id": "i-1", "intent_hash": "abc", "signer": "analyst", "decision": "approve"}
    expected = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert signing_payload("i-1", "abc", "analyst", "approve") == expected


def test_changing_segment_changes_hash():
    i = base_intent(segment="individual")
    assert compute_intent_hash({**i, "segment": "company"}) != i["intent_hash"]


def test_decision_dict_has_schema_fields():
    i = base_intent()
    d = evaluate(i, sign_all(i), verify, POLICY, now=NOW).to_decision()
    assert set(d) == {"intent_id", "status", "signatures", "human_required", "human_reason"}


# --- gate proof ---------------------------------------------------------------------

def gate_verify(payload, sig):
    return verify("gate", payload, sig)


def test_gate_proof_roundtrip():
    i = base_intent()
    sigs = sign_all(i)
    proof = make_gate_proof(i["intent_hash"], sigs, signer_fn(KEYS["gate"]))
    assert verify_gate_proof(proof, i["intent_hash"], sigs, gate_verify)


def test_gate_proof_fails_for_other_intent():
    i, j = base_intent(), base_intent(intent_id="i-2")
    sigs = sign_all(i)
    proof = make_gate_proof(i["intent_hash"], sigs, signer_fn(KEYS["gate"]))
    assert not verify_gate_proof(proof, j["intent_hash"], sigs, gate_verify)


def test_gate_proof_forged_by_rogue_fails():
    i = base_intent()
    sigs = sign_all(i)
    proof = make_gate_proof(i["intent_hash"], sigs, signer_fn(ROGUE))
    assert not verify_gate_proof(proof, i["intent_hash"], sigs, gate_verify)


def test_gate_proof_requires_all_three_approvals():
    i = base_intent()
    sigs = sign_all(i)[:2]
    proof = make_gate_proof(i["intent_hash"], sigs, signer_fn(KEYS["gate"]))
    assert not verify_gate_proof(proof, i["intent_hash"], sigs, gate_verify)


def test_gate_proof_garbage_is_false_not_crash():
    i = base_intent()
    assert not verify_gate_proof("not-base64!!", i["intent_hash"], sign_all(i), gate_verify)
