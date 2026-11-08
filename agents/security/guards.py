"""Input guards: pure, deterministic prompt-injection / abuse detection.

Layers (each one is explainable in one sentence for the jury):
1. Normalization  - lowercase, strip accents and zero-width chars, re-join
                    spaced letters ("i g n o r e"), decode leetspeak, so
                    cosmetic tricks do not hide a known pattern.
2. Patterns       - French + English + Tunisian darija rules for injection,
                    fake authority / discount abuse, data exfiltration.
3. Encoded data   - base64 blobs are decoded and scanned again.
4. Vaccines       - human-approved rules from the red team apply instantly.
5. LLM classifier - optional; any failure falls back to the rules above.

Risk is combined as 1 - prod(1 - w): independent signals add up, and the
message is blocked when risk >= 0.5.
"""
from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable

BLOCK_THRESHOLD = 0.5
MAX_SCAN_CHARS = 4000
MAX_SANITIZED_CHARS = 2000

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­"))
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
                       "7": "t", "@": "a", "$": "s", "!": "i"})
_SPACED_LETTERS = re.compile(r"\b(?:\w\s+){2,}\w\b")


@dataclass
class InputCheck:
    """Mirrors common.schemas.InputCheck."""
    allowed: bool
    risk_score: float
    reasons: list[str] = field(default_factory=list)
    sanitized_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------

def _rejoin_spaced(text: str) -> str:
    def join(m: re.Match) -> str:
        parts = m.group(0).split()
        return "".join(parts) if all(len(p) == 1 for p in parts) else m.group(0)
    return _SPACED_LETTERS.sub(join, text)


def normalize(text: str) -> str:
    text = (text or "").translate(_ZERO_WIDTH)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("’", "'").replace("`", "'")
    text = _rejoin_spaced(text)
    return re.sub(r"\s+", " ", text).strip()


def leet_decode(text: str) -> str:
    return text.translate(_LEET)


def sanitize(text: str) -> str:
    text = (text or "").translate(_ZERO_WIDTH)
    text = "".join(c for c in text
                   if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf"))
    return text.strip()[:MAX_SANITIZED_CHARS]


# --------------------------------------------------------------------------
# Pattern rules: (reason, weight, regex)
# --------------------------------------------------------------------------

_W = r"[^.?!\n]"  # "same sentence" filler

_RULES: list[tuple[str, float, re.Pattern]] = [(r, w, re.compile(p)) for r, w, p in [
    # --- prompt injection ---------------------------------------------------
    ("prompt_injection:ignore_rules", 0.9,
     rf"\b(ignore|disregard|forget|bypass|override|skip)\b{_W}{{0,40}}\b(instructions?|rules?|ru[il]es|guidelines|polic(?:y|ies)|restrictions?|prompt|directives?|constraints?)\b"),
    ("prompt_injection:ignore_rules_fr", 0.9,
     rf"\b(oublie[rz]?|ignore[rz]?|contourne[rz]?|ne tiens pas compte)\b{_W}{{0,40}}\b(regles?|instructions?|consignes?|directives?|limites?|restrictions?)\b"),
    ("prompt_injection:ignore_rules_darija", 0.9,
     rf"\b(ensa|nsa|insa|ansa|nsay)\b{_W}{{0,30}}\b(9awa3ed|9wa3ed|9awanin|9anoun|el 9anoun|regles?|instructions?|lois)\b"),
    ("prompt_injection:system_prompt", 0.85,
     r"\b(system|systeme|initial|hidden|secret|original)\s+(prompt|instructions?)\b|\bprompt\s+(systeme|system|initial|cache)\b"),
    ("prompt_injection:role_override", 0.85,
     r"\byou are now\b|\btu es maintenant\b|\bfrom now on,? you\b|\ba partir de maintenant,? tu\b|\bpretend (?:to be|you are)\b|\bfais semblant\b|\bjoue le role\b"),
    ("prompt_injection:jailbreak", 0.9,
     r"\b(developer|dev|god|admin|debug|unrestricted|sudo)\s+mode\b|\bmode\s+(developpeur|admin|debug|dieu)\b|\bjailbreak\b"),
    ("prompt_injection:fake_markup", 0.8,
     r"<\s*/?\s*(system|assistant|im_start)\b|\[(system|inst)\]|(^|\n)\s*system\s*:|#{2,}\s*(system|instruction)"),
    # --- fake authority / discount abuse ------------------------------------
    ("discount_abuse:fake_authority", 0.6,
     rf"\b(my|mon|ma|notre|our|el|l|the)\s*'?\s*(manager|boss|chef|directeur|director|responsable|supervisor|superviseur|ceo|patron|mudir|mdir|admin)\b{_W}{{0,40}}\b(approved?|approuve|valide|authori[sz]ed|autorise|said|told|dit|accepted|accepte|9alli|9al|qalli|confirmed|confirme|ok)\b"),
    ("discount_abuse:fake_authority", 0.6,
     r"\b(admin|manager) override\b|\bauthori[sz]ed by (?:the )?(admin|management|direction|manager)\b"),
    # --- exfiltration ---------------------------------------------------------
    ("exfiltration:secrets", 0.85,
     r"\b(api[\s_-]?key|private[\s_-]?key|secret[\s_-]?key|cle\s+(?:privee|api|secrete)|passwords?|passwd|mot de passe|mdp|access token|jwt|credentials?|identifiants)\b"),
    ("exfiltration:dump", 0.85,
     rf"\b(dump|export|exporte[rz]?)\b{_W}{{0,30}}\b(database|db|base de donnees|tables?|customers|clients)\b"),
]]

_OTHER_CUSTOMERS = re.compile(
    r"\b(other|others'?|all|every|autres?|tous les|toutes les)\s+(customers?|clients?|users?|utilisateurs?|clientes?)\b")
_PERSONAL_DATA = re.compile(
    r"\b(e-?mails?|mails?|phones?|telephones?|numeros?|address(?:es)?|adresses?|data|donnees|lists?|listes?|names|noms|cards?|cartes?|payments?|paiements?)\b")
_PERCENT = re.compile(r"(\d{1,3})\s*%")
_DISCOUNT_WORDS = re.compile(r"\b(remises?|discounts?|reductions?|off|promo|rabais|takhfidh|tkhfidh|soldes?)\b")
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
EXCESSIVE_DISCOUNT_PCT = 30


def _scan_variant(text: str) -> dict[str, float]:
    hits: dict[str, float] = {}
    for reason, weight, rx in _RULES:
        if rx.search(text):
            hits[reason] = max(hits.get(reason, 0.0), weight)
    if _OTHER_CUSTOMERS.search(text) and _PERSONAL_DATA.search(text):
        hits["exfiltration:other_customers"] = 0.85
    if _DISCOUNT_WORDS.search(text) and any(
            int(p) >= EXCESSIVE_DISCOUNT_PCT for p in _PERCENT.findall(text)):
        hits["discount_abuse:excessive_discount"] = 0.3  # haggling alone is not an attack
    return hits


def _decode_base64_blobs(raw: str) -> list[str]:
    out = []
    for blob in _B64_BLOB.findall(raw):
        padded = blob + "=" * (-len(blob) % 4)
        try:
            decoded = base64.b64decode(padded, validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        if decoded and sum(c.isprintable() for c in decoded) / len(decoded) > 0.9:
            out.append(decoded)
    return out


def _compile_extra(extra_rules: Iterable | None) -> list[tuple[str, re.Pattern]]:
    compiled = []
    for i, rule in enumerate(extra_rules or []):
        if isinstance(rule, str):
            rule_id, pattern = f"extra{i}", rule
        else:
            get = rule.get if isinstance(rule, dict) else lambda k, r=rule: getattr(r, k, None)
            rule_id, pattern = get("rule_id") or f"extra{i}", get("pattern")
        try:
            compiled.append((rule_id, re.compile(pattern, re.IGNORECASE)))
        except (re.error, TypeError):
            continue  # a broken vaccine must never take the guard down
    return compiled


def _variants(text: str) -> list[str]:
    norm = normalize(text)
    return list(dict.fromkeys([norm, leet_decode(norm)]))


def _scan(text: str, extra: list[tuple[str, re.Pattern]]) -> dict[str, float]:
    hits: dict[str, float] = {}
    for variant in _variants(text):
        for reason, weight in _scan_variant(variant).items():
            hits[reason] = max(hits.get(reason, 0.0), weight)
        for rule_id, rx in extra:
            if rx.search(variant):
                hits[f"vaccine:{rule_id}"] = 0.95
    return hits


def combine_risk(weights: Iterable[float]) -> float:
    remaining = 1.0
    for w in weights:
        remaining *= 1.0 - max(0.0, min(1.0, w))
    return round(1.0 - remaining, 3)


def check_input(text: str, extra_rules: Iterable | None = None,
                classifier: Callable[[str], float] | None = None) -> InputCheck:
    """Score a customer / agent supplied text. Pure and deterministic
    unless a classifier is passed."""
    raw = (text or "")[:MAX_SCAN_CHARS]
    extra = _compile_extra(extra_rules)
    hits = _scan(raw, extra)

    for decoded in _decode_base64_blobs(raw):
        inner = _scan(decoded, extra)
        if inner:
            hits["encoded_payload:base64"] = 0.9
            for reason, weight in inner.items():
                hits[reason] = max(hits.get(reason, 0.0), weight)

    if classifier is not None:
        try:
            score = float(classifier(raw))
            if score >= BLOCK_THRESHOLD:
                hits["llm_classifier"] = min(score, 1.0)
        except Exception:  # LLM down / slow: rules alone decide
            pass

    risk = combine_risk(hits.values())
    return InputCheck(allowed=risk < BLOCK_THRESHOLD, risk_score=risk,
                      reasons=sorted(hits), sanitized_text=sanitize(text))


def alert_type(check: InputCheck) -> str | None:
    """Map a blocked check to an Alert.type from common/schemas.py."""
    if check.allowed:
        return None
    for prefix, kind in (("exfiltration", "exfiltration"),
                         ("discount_abuse", "discount_abuse")):
        if any(r.startswith(prefix) for r in check.reasons) and not any(
                r.startswith("prompt_injection") for r in check.reasons):
            return kind
    return "prompt_injection"
