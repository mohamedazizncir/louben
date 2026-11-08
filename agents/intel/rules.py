"""Deterministic customer intelligence (fallback when no LLM). Used by Intel and Sales."""
from __future__ import annotations

import re
import unicodedata


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


FR_HINTS = {"je", "le", "la", "les", "un", "une", "est", "pour", "bonjour", "merci", "oui", "cher", "veux",
            "formation", "combien", "prix", "suis", "mon", "ma", "pas", "avec", "c'est", "salut", "trop",
            "et", "vous", "des", "de", "du", "avez", "que", "qui", "quoi", "comment", "nous", "votre", "vos", "dans",
            "au", "aux", "ce", "cette", "il", "elle", "on", "mais", "tres", "peux", "pouvez", "voudrais", "quel",
            "quelle", "d'accord", "ca", "j'ai", "moi", "prends", "fois", "plusieurs", "reconnus", "marche"}
EN_HINTS = {"i", "i'm", "i'll", "hello", "hi", "want", "the", "is", "to", "you", "your", "do", "how", "much", "have",
            "course", "can", "my", "me", "it", "what", "please", "thanks", "yes", "and", "for", "with", "learn", "too",
            "expensive", "deal", "fine", "take", "a", "are", "of", "in", "this", "that", "there", "would", "like"}


def detect_lang(text: str, default: str = "fr") -> str:
    """Count French vs English marker words; on a tie keep `default` (the conversation's current language)."""
    words = re.findall(r"[a-z']+", norm(text))
    fr = sum(w in FR_HINTS for w in words)
    en = sum(w in EN_HINTS for w in words)
    return "fr" if fr > en else "en" if en > fr else default


OBJECTIONS = {
    "price": ["cher", "expensive", "prix", "price", "budget", "ghali", "cout", "cost", "trop", "afford", "argent", "money", "flous"],
    "time": ["temps", "time", "busy", "horaire", "schedule", "occupe", "disponible", "weekend", "soir"],
    "level": ["niveau", "level", "difficile", "hard", "debutant", "beginner", "complique", "prerequis"],
    "trust": ["arnaque", "scam", "confiance", "trust", "reconnu", "certified", "certificat", "certificate", "serieux", "legit"],
    "payment": ["carte", "card", "paiement", "payment", "virement", "transfer", "installment", "tranche", "facilit"],
}
MOTIVATIONS = {
    "career": ["job", "emploi", "travail", "career", "carriere", "recrut", "hire", "salaire", "salary"],
    "skills": ["apprendre", "learn", "competence", "skill", "maitriser", "improve", "ameliorer"],
    "project": ["pfe", "projet", "project", "startup", "idee"],
    "certification": ["certif", "diplome", "attestation"],
}
NEEDS = {
    "ai": ["ia", "ai", "intelligence", "machine learning", "ml", "deep", "llm", "agent", "genai", "chatgpt"],
    "data": ["data", "donnee", "power bi", "sql", "analyse", "dashboard"],
    "web": ["web", "react", "site", "javascript", "node", "fullstack"],
    "pfe": ["pfe", "final year", "fin d'etude", "memoire"],
    "internship": ["stage", "internship", "summer", "ete"],
    "team_training": ["entreprise", "company", "equipe", "team", "employes", "employees", "salaries"],
}
SEGMENTS = [
    ("company", ["entreprise", "company", "equipe", "team", "employes", "employees", "rh", "hr", "societe", "salaries"]),
    ("student", ["etudiant", "student", "universite", "university", "ecole", "school", "pfe", "fac", "licence", "master"]),
    ("professional", ["developpeur", "developer", "ingenieur", "engineer", "travaille", "work", "job", "reconversion"]),
]
POSITIVE = ["merci", "thanks", "super", "great", "parfait", "perfect", "interesse", "interested", "top", "genial",
            "cool", "bien", "good", "ok", "oui", "yes", "d'accord", "excellent", "love", "j'aime"]
NEGATIVE = ["cher", "expensive", "non", "no", "pas interesse", "not interested", "nul", "bad", "arnaque", "scam",
            "probleme", "problem", "trop", "jamais", "never", "decu", "disappointed"]
ACCEPT = ["je prends", "i'll take", "i will take", "je confirme", "confirm", "ok pour", "d'accord", "deal",
          "on y va", "let's go", "lets go", "je paie", "je paye", "payer", "pay now", "buy", "acheter", "inscri", "yes please",
          "oui je", "ok je", "go ahead", "vas-y", "c'est bon"]


def _has(t: str, w: str) -> bool:
    """Short words need whole word match ('ai' must not match 'j'ai'); longer ones match as stems."""
    if len(w) <= 3:
        before = "[a-z']" if w == "ai" else "[a-z]"   # "j'ai" is French, not AI; "l'ia" is AI
        return re.search(rf"(?<!{before}){re.escape(w)}(?![a-z])", t) is not None
    return w in t


def _hits(text: str, table: dict[str, list[str]]) -> list[str]:
    t = norm(text)
    return [k for k, words in table.items() if any(_has(t, w) for w in words)]


def objections(text: str) -> list[str]:
    return _hits(text, OBJECTIONS)


def motivations(text: str) -> list[str]:
    return _hits(text, MOTIVATIONS)


def needs(text: str) -> list[str]:
    return _hits(text, NEEDS)


def segment(text: str, default: str = "individual") -> str:
    t = norm(text)
    for seg, words in SEGMENTS:
        if any(_has(t, w) for w in words):
            return seg
    return default


def sentiment(text: str) -> float:
    t = norm(text)
    pos = sum(1 for w in POSITIVE if _has(t, w))
    neg = sum(1 for w in NEGATIVE if _has(t, w))
    if pos + neg == 0:
        return 0.0
    return round((pos - neg) / (pos + neg), 2)


def conversation_sentiment(turns: list[str]) -> float:
    """Later turns weigh more, and accepting the offer is a strong positive signal:
    "c'est trop cher" followed by "d'accord, je prends" is a happy customer, not an unhappy one."""
    scores = [min(1.0, sentiment(t) + (0.8 if accepts(t) else 0)) for t in turns if t.strip()]
    if not scores:
        return 0.0
    weights = range(1, len(scores) + 1)
    return round(sum(w * s for w, s in zip(weights, scores)) / sum(weights), 2)


def accepts(text: str) -> bool:
    t = norm(text)
    return any(_has(t, w) for w in ACCEPT)


def wants_discount(text: str) -> float | None:
    """Return requested discount % if the customer asks for a specific one."""
    t = norm(text)
    m = re.search(r"(\d{1,3})\s*(%|pour ?cent|percent)", t)
    if m:
        return float(m.group(1))
    if any(w in t for w in ["remise", "reduction", "discount", "promo", "rabais", "moins cher", "cheaper"]):
        return -1.0  # asks for "a discount" without a number
    return None


def wants_installments(text: str) -> bool:
    t = norm(text)
    return any(w in t for w in ["tranche", "installment", "plusieurs fois", "3 fois", "2 fois", "facilit", "mensual", "monthly"])


def match_product(text: str, catalog: list[dict]) -> dict | None:
    t = norm(text)
    best, score = None, 0
    for p in catalog:
        s = sum(2 if len(tag) > 3 else 1 for tag in p.get("tags", []) if re.search(rf"\b{re.escape(norm(tag))}\b", t))
        s += sum(1 for w in norm(p["name"]).split() if len(w) > 3 and w in t)
        if s > score:
            best, score = p, s
    return best


def satisfaction_from(sent: float, outcome: str) -> int:
    base = 3 + sent * 1.5 + (0.8 if outcome == "purchase_started" else 0) - (0.8 if outcome == "not_interested" else 0)
    return int(max(1, min(5, round(base))))


def interest_score(text: str, outcome: str) -> float:
    s = 0.3
    t = norm(text)
    if any(w in t for w in ["combien", "how much", "prix", "price", "quand", "when", "start", "commence", "inscri"]):
        s += 0.2
    if outcome == "interested":
        s += 0.2
    if outcome == "purchase_started":
        s = 0.95
    if outcome == "not_interested":
        s = 0.1
    return round(min(1.0, s + max(0, sentiment(text)) * 0.2), 2)
