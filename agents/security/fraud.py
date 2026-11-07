"""Fraud rules used by the Security signature in the Multisig Gate.

Hard fraud (velocity, wrong amount, discount above policy, token switching)
makes Security refuse to sign. Soft anomalies (unusual amount, recent alerts
on the customer) let Security sign but raise the risk level, which sends the
intent to a human. All functions are pure: state is passed in.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field

from agents.security.offers import max_discount_for

VELOCITY_WINDOW_S = 60
VELOCITY_LIMIT = 3
TOKEN_SWITCH_MIN_REFUSALS = 2
Z_THRESHOLD = 3.5
Z_MIN_HISTORY = 5
AMOUNT_TOLERANCE = 0.01

SEVERITY_ORDER = ["none", "low", "medium", "high", "critical"]
REFUSE_AT = "high"


@dataclass
class FraudFlag:
    kind: str          # fine grained rule name
    alert_type: str    # one of the Alert.type values in PLAN.md Section 7
    severity: str      # low | medium | high | critical
    reason: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FraudContext:
    list_price: float
    segment: str
    policy: dict
    now: float
    recent_intent_times: list[float] = field(default_factory=list)
    past_attempts: list[dict] = field(default_factory=list)   # [{token, status}]
    amount_history: list[float] = field(default_factory=list)
    recent_alert_count: int = 0


@dataclass
class FraudReport:
    approve: bool
    risk_level: str
    flags: list[FraudFlag]

    @property
    def reason(self) -> str:
        return "; ".join(f.reason for f in self.flags) or "no fraud rule fired"

    def to_dict(self) -> dict:
        return {"approve": self.approve, "risk_level": self.risk_level,
                "reason": self.reason, "flags": [f.to_dict() for f in self.flags]}


# --------------------------------------------------------------------------
# Individual rules
# --------------------------------------------------------------------------

def velocity(previous_times: list[float], now: float,
             window: float = VELOCITY_WINDOW_S, limit: int = VELOCITY_LIMIT) -> FraudFlag | None:
    count = sum(1 for t in previous_times if now - window <= t <= now) + 1
    if count > limit:
        return FraudFlag("velocity", "velocity", "high",
                         f"{count} payment intents in {window:g}s (limit {limit})",
                         {"count": count, "window_s": window})
    return None


def amount_mismatch(amount: float, list_price: float, discount_pct: float,
                    tolerance: float = AMOUNT_TOLERANCE) -> FraudFlag | None:
    expected = round(list_price * (1 - discount_pct / 100), 3)
    if abs(float(amount) - expected) > tolerance:
        return FraudFlag("amount_mismatch", "amount_mismatch", "critical",
                         f"amount {amount} != catalog price minus discount {expected}",
                         {"amount": amount, "expected": expected})
    return None


def discount_above_policy(discount_pct: float, segment: str, policy: dict) -> FraudFlag | None:
    cap = max_discount_for(segment, policy)
    if discount_pct > cap:
        return FraudFlag("discount_above_policy", "discount_abuse", "high",
                         f"discount {discount_pct:g}% above policy {cap:g}% for '{segment}'",
                         {"discount_pct": discount_pct, "max": cap})
    return None


def token_switching(new_token: str, past_attempts: list[dict],
                    min_refusals: int = TOKEN_SWITCH_MIN_REFUSALS) -> FraudFlag | None:
    """Card testing pattern: several refusals, then a different token."""
    refused = [a for a in past_attempts if a.get("status") == "refused"]
    if len(refused) >= min_refusals and new_token not in {a.get("token") for a in refused}:
        return FraudFlag("token_switching", "velocity", "high",
                         f"new payment token after {len(refused)} refusals",
                         {"refusals": len(refused)})
    return None


def amount_anomaly(amount: float, history: list[float],
                   z_threshold: float = Z_THRESHOLD) -> FraudFlag | None:
    """Robust z-score (median / MAD, Iglewicz-Hoaglin): a few past outliers
    cannot inflate the baseline and hide a new one."""
    if len(history) < Z_MIN_HISTORY:
        return None
    median = statistics.median(history)
    mad = statistics.median(abs(h - median) for h in history)
    if mad:
        z = 0.6745 * (amount - median) / mad
        anomalous = abs(z) >= z_threshold
    else:  # all past amounts identical: flag a > 50% deviation
        z = None
        anomalous = abs(amount - median) > 0.5 * abs(median)
    if anomalous:
        shown = f"robust z-score {z:.1f}" if z is not None else "constant history"
        return FraudFlag("amount_anomaly", "amount_mismatch", "medium",
                         f"unusual amount {amount} ({shown} vs median {median:.0f})",
                         {"robust_z": round(z, 2) if z is not None else None, "median": median})
    return None


def recent_alerts(count: int) -> FraudFlag | None:
    if count > 0:
        return FraudFlag("recent_alerts", "velocity", "medium",
                         f"{count} recent security alert(s) on this customer",
                         {"count": count})
    return None


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def _max_severity(flags: list[FraudFlag]) -> str:
    return max((f.severity for f in flags), key=SEVERITY_ORDER.index, default="none")


def evaluate(intent, ctx: FraudContext) -> FraudReport:
    get = intent.get if isinstance(intent, dict) else lambda k, d=None: getattr(intent, k, d)
    amount = float(get("amount"))
    discount = float(get("discount_pct", 0) or 0)
    token = get("payment_token", "")

    candidates = [
        velocity(ctx.recent_intent_times, ctx.now),
        amount_mismatch(amount, ctx.list_price, discount),
        discount_above_policy(discount, ctx.segment, ctx.policy),
        token_switching(token, ctx.past_attempts),
        amount_anomaly(amount, ctx.amount_history),
        recent_alerts(ctx.recent_alert_count),
    ]
    flags = [f for f in candidates if f is not None]
    level = _max_severity(flags)
    approve = SEVERITY_ORDER.index(level) < SEVERITY_ORDER.index(REFUSE_AT)
    return FraudReport(approve=approve, risk_level=level, flags=flags)
