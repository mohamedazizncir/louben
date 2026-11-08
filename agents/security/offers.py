"""Offer guardrail: a discount is only valid if the signed company policy
allows it for the customer's segment. Pure function, no I/O."""
from __future__ import annotations

from dataclasses import asdict, dataclass

PRICE_TOLERANCE = 0.01  # TND
DEFAULT_INSTALLMENTS = (1, 2, 3)


@dataclass
class OfferCheck:
    """Mirrors common.schemas.OfferCheck."""
    allowed: bool
    max_discount_pct: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def max_discount_for(segment: str | None, policy: dict) -> float:
    caps = policy.get("max_discount_pct", 0)
    if isinstance(caps, dict):
        return float(caps.get(segment or "default", caps.get("default", 0)))
    return float(caps)


def check_offer(offer, segment: str | None, policy: dict,
                catalog_price: float | None = None) -> OfferCheck:
    cap = max_discount_for(segment, policy)

    def refuse(reason: str) -> OfferCheck:
        return OfferCheck(allowed=False, max_discount_pct=cap, reason=reason)

    try:
        list_price = float(_get(offer, "list_price"))
        discount = float(_get(offer, "discount_pct"))
        final_price = float(_get(offer, "final_price"))
        installments = int(_get(offer, "installments"))
    except (TypeError, ValueError):
        return refuse("malformed offer: missing or invalid field")

    if catalog_price is not None and abs(list_price - float(catalog_price)) > PRICE_TOLERANCE:
        return refuse(f"list_price {list_price} does not match catalog price {catalog_price}")
    if discount < 0:
        return refuse("negative discount")
    if discount > cap:
        return refuse(f"discount {discount:g}% above policy max {cap:g}% for segment '{segment}'")
    expected = round(list_price * (1 - discount / 100), 3)
    if abs(final_price - expected) > PRICE_TOLERANCE:
        return refuse(f"final_price {final_price} != expected {expected}")
    allowed_inst = policy.get("installments_allowed", policy.get("allowed_installments", DEFAULT_INSTALLMENTS))
    if installments not in allowed_inst:
        return refuse(f"installments {installments} not in {list(allowed_inst)}")
    return OfferCheck(allowed=True, max_discount_pct=cap, reason="within policy")
