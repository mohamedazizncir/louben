"""Shared data models (PLAN.md Section 7). Owner: A. FROZEN after CP0: only add optional fields."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Product(BaseModel):
    product_id: str
    name: str
    description: str = ""
    list_price: float
    currency: str = "TND"
    tags: list[str] = []
    type: str = "training"
    duration: str = ""


class Customer(BaseModel):
    customer_id: str
    name: str
    email_masked: str = ""
    segment: str = "individual"


class ChatTurn(BaseModel):
    role: Literal["customer", "agent"]
    text: str
    ts: str = Field(default_factory=now_iso)


class Interaction(BaseModel):
    interaction_id: str = Field(default_factory=lambda: new_id("int-"))
    customer_id: str
    channel: Literal["voice", "text"] = "text"
    turns: list[ChatTurn] = []
    product_id: Optional[str] = None
    outcome: Literal["interested", "not_interested", "purchase_started", "open"] = "open"
    started_at: str = Field(default_factory=now_iso)
    ended_at: Optional[str] = None
    segment: Optional[str] = None


class IntelReport(BaseModel):
    interaction_id: str
    customer_id: str
    needs: list[str] = []
    objections: list[str] = []
    motivations: list[str] = []
    sentiment: float = 0.0
    interest_score: float = 0.0
    satisfaction: Optional[int] = None
    segment: str = "individual"
    churn_risk: float = 0.0


class Offer(BaseModel):
    product_id: str
    list_price: float
    discount_pct: float = 0
    final_price: float
    installments: int = 1


class OfferCheck(BaseModel):
    allowed: bool
    max_discount_pct: float
    reason: str = ""


class InputCheck(BaseModel):
    allowed: bool
    risk_score: float = 0.0
    reasons: list[str] = []
    sanitized_text: str = ""


class PaymentIntent(BaseModel):
    intent_id: str = Field(default_factory=lambda: new_id("pi-"))
    customer_id: str
    product_id: str
    amount: float
    discount_pct: float = 0
    installments: int = 1
    payment_token: str = "tok_visa"
    nonce: str = Field(default_factory=lambda: uuid.uuid4().hex)
    expires_at: str = ""
    created_at: str = Field(default_factory=now_iso)
    intent_hash: str = ""
    segment: Optional[str] = None


class Signature(BaseModel):
    intent_id: str
    intent_hash: str
    signer: Literal["payment", "security", "analyst", "human"]
    decision: Literal["approve", "refuse"]
    reason: str = ""
    signature_b64: str = ""
    ts: str = Field(default_factory=now_iso)
    risk_level: Optional[str] = None      # set by security.sign (B), optional field added after CP0


class GateDecision(BaseModel):
    intent_id: str
    status: Literal["collecting", "pending_human", "approved", "rejected", "executed"]
    signatures: list[Signature] = []
    human_required: bool = False
    human_reason: Optional[str] = None
    payment_status: Optional[str] = None


class PaymentResult(BaseModel):
    intent_id: str
    status: Literal["succeeded", "refused", "pending"]
    provider: Literal["simulated", "stripe_test"] = "simulated"
    provider_ref: str = ""
    ts: str = Field(default_factory=now_iso)


AlertType = Literal[
    "prompt_injection", "discount_abuse", "velocity", "amount_mismatch", "spoofed_agent",
    "scope_violation", "replay", "tampering", "exfiltration", "fake_approval",
]


class Alert(BaseModel):
    alert_id: str = Field(default_factory=lambda: new_id("al-"))
    type: str
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    source: str = ""
    details: dict[str, Any] = {}
    requires_human: bool = False
    ts: str = Field(default_factory=now_iso)


class Recommendation(BaseModel):
    rec_id: str = Field(default_factory=lambda: new_id("rec-"))
    title: str
    rationale: str
    evidence: dict[str, Any] = {}
    expected_impact: str = ""
    status: Literal["proposed", "approved", "rejected"] = "proposed"


class AttackResult(BaseModel):
    attack_id: str = Field(default_factory=lambda: new_id("atk-"))
    name: str
    category: str
    target: str
    payload_summary: str = ""
    blocked: bool
    blocked_by: Optional[str] = None
    ts: str = Field(default_factory=now_iso)


class ProposedRule(BaseModel):
    rule_id: str = Field(default_factory=lambda: new_id("rule-"))
    from_attack_id: str = ""
    pattern: str
    description: str = ""
    status: Literal["proposed", "approved", "rejected"] = "proposed"


class Event(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("ev-"))
    ts: str = Field(default_factory=now_iso)
    source: str
    type: str
    severity: Literal["info", "warning", "critical"] = "info"
    data: dict[str, Any] = {}
