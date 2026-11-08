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
    assert rules.detect_lang("Et vous avez des certificats reconnus ?") == "fr"
    assert rules.detect_lang("ok I'll take it") == "en"
    assert rules.detect_lang("ok", "en") == "en"                     # no signal: keep the current language
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


def test_sentiment_reads_the_whole_conversation():
    from agents.intel.main import clean_llm, fallback_report
    from common.schemas import ChatTurn, Interaction
    # a price objection followed by a purchase is a happy customer
    assert rules.conversation_sentiment(["Bonjour, je veux apprendre l'IA", "C'est trop cher", "D'accord, je prends"]) > 0
    assert rules.conversation_sentiment(["c'est trop cher", "non merci, jamais"]) < 0
    it = Interaction(interaction_id="i1", customer_id="c1", channel="voice", outcome="purchase_started",
                     started_at="2026-11-08T10:00:00+00:00",
                     turns=[ChatTurn(role="customer", text=x) for x in ["je suis étudiant", "trop cher", "ok je prends"]])
    base = fallback_report(it)
    assert base.satisfaction >= 3 and base.segment == "student"
    # free text LLM labels are dropped so charts keep stable categories
    out = clean_llm({"objections": ["C'est trop cher", "TIME"], "segment": "Étudiant"}, base)
    assert out["objections"] == ["price", "time"] and out["segment"] == "student"


def _signed(monkeypatch, tmp_path, **intent):
    import asyncio
    from agents.analyst import main as analyst
    from common import crypto
    if not crypto.keys_exist():
        crypto.generate_keys()
    db = store.connect(tmp_path / f"sign-{len(list(tmp_path.iterdir()))}.db")   # fresh history per call
    monkeypatch.setattr(analyst, "DB", db)
    for i in range(intent.pop("refused", 0)):
        store.ingest(db, {"type": "payment.status", "ts": "2026-11-08T10:00:00+00:00", "data": {
            "intent_id": f"old{i}", "status": "refused", "amount": 500, "customer_id": "c1", "product_id": "genai-agents"}})
    pi = {"customer_id": "c1", "product_id": "genai-agents", "amount": 675, "intent_hash": "h" * 64, **intent}
    sig = asyncio.run(analyst.sign(pi, {}))
    payload = {k: sig[k] for k in ("intent_id", "intent_hash", "signer", "decision")}
    assert crypto.verify_obj("analyst", payload, sig["signature_b64"])     # every decision is signed
    return sig


def test_analyst_sign_rules(monkeypatch, tmp_path):
    assert _signed(monkeypatch, tmp_path, discount_pct=10, segment="student")["decision"] == "approve"
    assert _signed(monkeypatch, tmp_path, discount_pct=15, segment="student")["decision"] == "approve"   # student max 15
    assert _signed(monkeypatch, tmp_path, discount_pct=15, segment="professional")["decision"] == "refuse"
    assert _signed(monkeypatch, tmp_path, discount_pct=90, segment="company")["decision"] == "refuse"
    assert _signed(monkeypatch, tmp_path, discount_pct=0, installments=6)["decision"] == "refuse"
    assert _signed(monkeypatch, tmp_path, discount_pct=0, refused=1)["decision"] == "approve"
    assert _signed(monkeypatch, tmp_path, discount_pct=0, refused=2)["decision"] == "refuse"
