from agents.security.fraud import (
    FraudContext, amount_anomaly, amount_mismatch, discount_above_policy,
    evaluate, token_switching, velocity,
)

POLICY = {"max_discount_pct": {"default": 10, "company": 20}}
NOW = 1_000_000.0


# --- velocity ---------------------------------------------------------------

def test_three_intents_in_a_minute_is_fine():
    assert velocity([NOW - 30, NOW - 10], NOW) is None


def test_fourth_intent_within_60s_is_flagged():
    flag = velocity([NOW - 50, NOW - 30, NOW - 10], NOW)
    assert flag and flag.alert_type == "velocity" and flag.severity == "high"


def test_old_intents_do_not_count_for_velocity():
    assert velocity([NOW - 300, NOW - 200, NOW - 100], NOW) is None


# --- amount mismatch --------------------------------------------------------

def test_amount_matching_catalog_minus_discount_is_ok():
    assert amount_mismatch(450.0, 500.0, 10) is None


def test_amount_lower_than_expected_is_critical():
    flag = amount_mismatch(1.0, 500.0, 10)
    assert flag and flag.alert_type == "amount_mismatch" and flag.severity == "critical"


# --- discount policy --------------------------------------------------------

def test_discount_within_policy_ok():
    assert discount_above_policy(10, "new", POLICY) is None


def test_discount_above_policy_flagged():
    flag = discount_above_policy(90, "new", POLICY)
    assert flag and flag.alert_type == "discount_abuse"


# --- token switching ----------------------------------------------------------

def test_new_token_after_two_refusals_is_flagged():
    past = [{"token": "tok_declined", "status": "refused"},
            {"token": "tok_declined", "status": "refused"}]
    flag = token_switching("tok_visa", past)
    assert flag and flag.kind == "token_switching"


def test_retry_after_single_refusal_is_fine():
    assert token_switching("tok_visa", [{"token": "tok_declined", "status": "refused"}]) is None


def test_same_token_after_refusals_is_not_switching():
    past = [{"token": "tok_visa", "status": "refused"}] * 3
    assert token_switching("tok_visa", past) is None


# --- amount anomaly -----------------------------------------------------------

HISTORY = [400, 420, 450, 380, 410, 430, 405, 440, 395, 415]


def test_typical_amount_is_not_anomalous():
    assert amount_anomaly(425, HISTORY) is None


def test_extreme_amount_is_anomalous_medium_risk():
    flag = amount_anomaly(5000, HISTORY)
    assert flag and flag.kind == "amount_anomaly" and flag.severity == "medium"


def test_short_history_skips_zscore():
    assert amount_anomaly(5000, [400, 410]) is None


def test_robust_zscore_resists_masking_by_a_past_outlier():
    # two old 5000 TND payments inflate mean/std; median/MAD still sees 4800 as abnormal
    assert amount_anomaly(4800, HISTORY + [5000, 5000]) is not None


# --- evaluate -------------------------------------------------------------------

def ctx(**kw):
    base = dict(list_price=500.0, segment="new", policy=POLICY, now=NOW,
                recent_intent_times=[], past_attempts=[], amount_history=HISTORY,
                recent_alert_count=0)
    base.update(kw)
    return FraudContext(**base)


def intent(**kw):
    base = {"amount": 450.0, "discount_pct": 10, "payment_token": "tok_visa"}
    base.update(kw)
    return base


def test_clean_intent_is_approved_with_no_risk():
    report = evaluate(intent(), ctx())
    assert report.approve and report.risk_level == "none" and report.flags == []


def test_hard_fraud_refuses():
    report = evaluate(intent(amount=1.0), ctx())
    assert not report.approve
    assert report.risk_level == "critical"


def test_soft_anomaly_approves_but_raises_risk_for_human():
    report = evaluate(intent(), ctx(recent_alert_count=1))
    assert report.approve
    assert report.risk_level == "medium"


def test_velocity_attack_refused():
    report = evaluate(intent(), ctx(recent_intent_times=[NOW - 15, NOW - 10, NOW - 5]))
    assert not report.approve
    assert any(f.alert_type == "velocity" for f in report.flags)
