import re

import pytest

from agents.redteam.attacks import (
    ATTACKS, BENIGN_SAMPLES, get_attacks, immunity_score, make_result,
    propose_rule, run_local, run_local_campaign,
)
from agents.security.guards import check_input, normalize

ALERT_TYPES = {"prompt_injection", "discount_abuse", "velocity", "amount_mismatch",
               "spoofed_agent", "scope_violation", "replay", "tampering",
               "exfiltration", "fake_approval"}


# --- library shape ------------------------------------------------------------

def test_library_covers_the_11_planned_attacks_plus_a_novel_one():
    assert len(ATTACKS) >= 12
    assert len({a.attack_id for a in ATTACKS}) == len(ATTACKS)
    assert len({a.name for a in ATTACKS}) == len(ATTACKS)


def test_every_attack_category_is_an_alert_type():
    assert {a.category for a in ATTACKS} <= ALERT_TYPES


def test_no_real_card_numbers_in_payloads():
    for a in ATTACKS:
        assert not re.search(r"\b\d{13,19}\b", str(a.payload)), a.name


def test_get_attacks_all_and_by_name():
    assert len(get_attacks("all")) == len(ATTACKS)
    picked = get_attacks(["replay", "tampering", "does_not_exist"])
    assert [a.name for a in picked] == ["replay", "tampering"]


# --- results / score -------------------------------------------------------------

def test_make_result_has_schema_fields_and_short_summary():
    r = make_result(ATTACKS[0], blocked=True, blocked_by="security.check_input")
    assert set(r) == {"attack_id", "name", "category", "target", "payload_summary",
                      "blocked", "blocked_by", "ts"}
    assert len(r["payload_summary"]) <= 120


def test_immunity_score():
    rs = [{"blocked": True}, {"blocked": True}, {"blocked": False}, {"blocked": True}]
    assert immunity_score(rs) == 0.75
    assert immunity_score([]) == 0.0


# --- local execution ---------------------------------------------------------------

@pytest.mark.parametrize("attack", [a for a in ATTACKS if not a.novel], ids=lambda a: a.name)
def test_known_attacks_are_blocked_locally(attack):
    result = run_local(attack)
    assert result["blocked"], attack.name
    assert result["blocked_by"]


def test_novel_attack_passes_the_first_time():
    novel = [a for a in ATTACKS if a.novel]
    assert novel, "need at least one attack that gets through for the live vaccine moment"
    assert not run_local(novel[0])["blocked"]


# --- vaccines -------------------------------------------------------------------------

def novel_attack():
    return next(a for a in ATTACKS if a.novel)


def test_fallback_rule_blocks_the_attack_once_approved():
    attack = novel_attack()
    rule = propose_rule(attack)
    assert rule["status"] == "proposed" and rule["from_attack_id"] == attack.attack_id
    assert set(rule) == {"rule_id", "from_attack_id", "pattern", "description", "status"}
    assert not check_input(attack.payload, extra_rules=[rule]).allowed


def test_fallback_rule_does_not_block_benign_messages():
    rule = propose_rule(novel_attack())
    for text in BENIGN_SAMPLES:
        assert check_input(text, extra_rules=[rule]).allowed, text


def test_llm_rule_is_used_when_valid():
    attack = novel_attack()
    words = normalize(attack.payload).split()
    llm_pattern = re.escape(words[0]) + r".{0,80}" + re.escape(words[-1])
    rule = propose_rule(attack, llm=lambda payload: llm_pattern)
    assert rule["pattern"] == llm_pattern


@pytest.mark.parametrize("bad", ["((", ".*", "zzz_never_matches", ""])
def test_bad_llm_rule_falls_back(bad):
    attack = novel_attack()
    rule = propose_rule(attack, llm=lambda payload: bad)
    assert rule["pattern"] != bad
    assert not check_input(attack.payload, extra_rules=[rule]).allowed


def test_llm_exception_falls_back():
    def boom(_):
        raise RuntimeError("timeout")
    assert propose_rule(novel_attack(), llm=boom)["pattern"]


# --- full offline campaign (demo fallback) ----------------------------------------------

def test_campaign_then_vaccine_reaches_full_immunity():
    first = run_local_campaign()
    assert 0 < first["immunity_score"] < 1
    assert first["proposed_rules"], "a passing attack must produce a vaccine"

    approved = [{**r, "status": "approved"} for r in first["proposed_rules"]]
    second = run_local_campaign(extra_rules=approved)
    assert second["immunity_score"] == 1.0
    assert second["proposed_rules"] == []
