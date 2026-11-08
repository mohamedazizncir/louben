from agents.strategy.rules import build, numbers_grounded, summarize_reports

POLICY = {"max_discount_pct": {"individual": 10, "student": 15, "company": 20}, "human_discount_pct": 10}

KPIS = {
    "interactions_total": 321, "interested_total": 160, "conversion_rate": 0.178,
    "top_objections": [{"label": "price", "count": 137}, {"label": "time", "count": 62},
                       {"label": "level", "count": 44}, {"label": "payment", "count": 30},
                       {"label": "trust", "count": 30}],
    "payments": {"succeeded": 57, "refused": 12, "pending": 7},
    "revenue_simulated": 48662.5, "avg_satisfaction": 3.23,
    "satisfaction_dist": {"1": 3, "2": 60, "3": 129, "4": 117, "5": 12},
    "alerts_total": 57, "alerts_by_type": {"prompt_injection": 17, "discount_abuse": 6, "velocity": 4},
    "by_segment": {"student": 149, "professional": 85}, "by_channel": {"text": 197, "voice": 124},
    "revenue_by_product": {"corporate-ai-pack": 15200.0, "ml-bootcamp": 8160.0, "ai-fundamentals": 6052.5},
}


def test_three_recommendations_with_evidence():
    recs = build(KPIS, [], POLICY)
    assert len(recs) == 3
    for r in recs:
        assert r["evidence"] and r["title"] and r["rationale"] and r["status"] == "proposed"


def test_price_recommendation_quotes_the_share():
    price = next(r for r in build(KPIS, [], POLICY) if "price" in r["evidence"].get("kind", ""))
    assert "45%" in price["rationale"] and "303" in price["rationale"]


def test_exactly_one_security_aware_recommendation():
    recs = build(KPIS, [], POLICY)
    sec = [r for r in recs if r["evidence"].get("security")]
    assert len(sec) == 1
    assert "23" in sec[0]["rationale"]  # 17 injection + 6 discount abuse attempts


def test_security_recommendation_even_without_alerts():
    k = {**KPIS, "alerts_by_type": {}, "alerts_total": 0}
    assert any(r["evidence"].get("security") for r in build(k, [], POLICY))


def test_empty_kpis_do_not_crash():
    empty = {"interactions_total": 0, "top_objections": [], "payments": {}, "alerts_by_type": {}}
    recs = build(empty, [], POLICY)
    assert 1 <= len(recs) <= 3


def test_redteam_reports_are_ignored():
    reports = [{"customer_id": "redteam-x", "objections": ["price"], "needs": ["hack"]},
               {"customer_id": "c-1", "objections": ["time"], "needs": ["python"]}]
    s = summarize_reports(reports)
    assert s["count"] == 1 and s["objections"] == {"time": 1}


def test_numbers_grounded_rejects_invented_numbers():
    evidence = {"price_objections": 137, "objections_total": 303, "share_pct": 45}
    assert numbers_grounded("Price is 45% of 303 objections (137)", evidence)
    assert not numbers_grounded("Price is 80% of objections", evidence)
