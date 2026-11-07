"""Unit tests for the business side (no services needed). Run: python -m pytest tests/business -q"""
from agents.analyst import store
from agents.intel import rules
from common import config

KPI_KEYS = ["interactions_total", "interested_total", "conversion_rate", "top_objections", "payments",
            "revenue_simulated", "avg_satisfaction", "alerts_total", "alerts_by_type", "revenue_forecast_7d",
            "recent_recommendations"]


def test_intel_rules_fr_en():
    assert rules.detect_lang("Bonjour je veux une formation") == "fr"
    assert rules.detect_lang("Hello I want a course") == "en"
    assert "price" in rules.objections("c'est trop cher pour moi")
    assert "price" in rules.objections("that's too expensive")
    assert rules.segment("je suis étudiant") == "student"
    assert rules.segment("training for my company team") == "company"
    assert "ai" not in rules.needs("j'ai une question")          # 'ai' must not match "j'ai"
    assert rules.wants_discount("donne moi 90% de remise") == 90
    assert rules.accepts("ok je prends")


def test_product_matching():
    cat = config.catalog()
    assert rules.match_product("je veux apprendre les agents IA et les LLM", cat)["product_id"] == "genai-agents"
    assert rules.match_product("formation pour mon equipe en entreprise", cat)["product_id"] == "corporate-ai-pack"


def test_kpis_keys_and_ingest(tmp_path):
    c = store.connect(tmp_path / "b.db")
    store.ingest(c, {"type": "interaction.ended", "ts": "2026-11-08T10:00:00+00:00", "data": {
        "interaction_id": "i1", "customer_id": "c1", "channel": "voice", "product_id": "ai-fundamentals",
        "outcome": "purchase_started", "segment": "student", "turns": []}})
    store.ingest(c, {"type": "intel.report", "data": {"interaction_id": "i1", "customer_id": "c1",
                                                      "objections": ["price"], "satisfaction": 4}})
    store.ingest(c, {"type": "payment.status", "ts": "2026-11-08T10:01:00+00:00", "data": {
        "intent_id": "p1", "status": "succeeded", "amount": 405, "customer_id": "c1", "product_id": "ai-fundamentals"}})
    k = store.kpis(c)
    for key in KPI_KEYS:
        assert key in k
    assert k["payments"]["succeeded"] == 1 and k["revenue_simulated"] == 405
    assert k["top_objections"][0]["label"] == "price"
    assert len(k["revenue_forecast_7d"]) == 7
    assert store.drilldown(c, "payments:succeeded")["rows"]
    assert store.knowledge(c)["nodes"]


def test_filters(tmp_path):
    c = store.connect(tmp_path / "b.db")
    for i, seg in enumerate(["student", "company"]):
        store.ingest(c, {"type": "interaction.ended", "ts": "2026-11-08T10:00:00+00:00", "data": {
            "interaction_id": f"i{i}", "customer_id": f"c{i}", "channel": "text", "outcome": "open", "segment": seg, "turns": []}})
    assert store.kpis(c, {"segment": "student"})["interactions_total"] == 1
    assert store.kpis(c, {"from": "2026-12-01"})["interactions_total"] == 0
