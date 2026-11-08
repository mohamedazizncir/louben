import pytest

from agents.security.offers import check_offer, max_discount_for

POLICY = {
    "max_discount_pct": {"default": 10, "new": 10, "student": 15, "company": 20},
    "human_threshold": 1000,
    "human_discount_pct": 10,
    "allowed_installments": [1, 2, 3],
}


def offer(list_price=500.0, discount_pct=10, final_price=None, installments=3):
    if final_price is None:
        final_price = round(list_price * (1 - discount_pct / 100), 3)
    return {"product_id": "p1", "list_price": list_price, "discount_pct": discount_pct,
            "final_price": final_price, "installments": installments}


def test_max_discount_uses_segment_then_default():
    assert max_discount_for("student", POLICY) == 15
    assert max_discount_for("unknown", POLICY) == 10
    assert max_discount_for("new", {"max_discount_pct": 5}) == 5


def test_allowed_offer_within_policy():
    r = check_offer(offer(discount_pct=10), "new", POLICY)
    assert r.allowed
    assert r.max_discount_pct == 10


def test_discount_above_segment_max_is_refused():
    r = check_offer(offer(discount_pct=90), "new", POLICY)
    assert not r.allowed
    assert "discount" in r.reason


def test_segment_with_higher_cap_allows_bigger_discount():
    assert check_offer(offer(discount_pct=20), "company", POLICY).allowed


def test_negative_discount_is_refused():
    assert not check_offer(offer(discount_pct=-5), "new", POLICY).allowed


def test_final_price_must_match_discount():
    r = check_offer(offer(discount_pct=10, final_price=1.0), "new", POLICY)
    assert not r.allowed
    assert "final_price" in r.reason


def test_list_price_must_match_catalog_when_given():
    r = check_offer(offer(list_price=1.0, discount_pct=0), "new", POLICY, catalog_price=500.0)
    assert not r.allowed
    assert "catalog" in r.reason


@pytest.mark.parametrize("n", [0, 4, 12])
def test_installments_outside_policy_are_refused(n):
    assert not check_offer(offer(installments=n), "new", POLICY).allowed


def test_offer_object_with_attributes_is_accepted():
    class O:
        product_id, list_price, discount_pct, final_price, installments = "p1", 100.0, 0, 100.0, 1
    assert check_offer(O(), "new", POLICY).allowed


def test_missing_field_is_refused_not_crashing():
    assert not check_offer({"discount_pct": 5}, "new", POLICY).allowed


def test_to_dict_matches_schema_fields():
    assert set(check_offer(offer(), "new", POLICY).to_dict()) == {"allowed", "max_discount_pct", "reason"}


def test_reads_installments_allowed_key_from_real_policy_file():
    policy = {"max_discount_pct": {"individual": 10}, "installments_allowed": [1, 2]}
    assert not check_offer(offer(installments=3), "individual", policy).allowed
    assert check_offer(offer(installments=2), "individual", policy).allowed
