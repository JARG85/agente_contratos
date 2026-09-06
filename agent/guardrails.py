"""Controles de seguridad y de alcance. Se ejecutan ANTES de invocar el LLM,
para que ningún caso fuera de alcance dependa de que el modelo "se porte bien".
"""
import re
import unicodedata

CONFIDENCE_THRESHOLD = 0.7

_INJECTION_PATTERNS = [
    r"ignora?\s+(tu[s]?\s+)?(instruccion|contexto|regla|prompt)",
    r"ignore\s+(your\s+)?(previous\s+)?(instruction|context|rule|prompt)",
    r"olvida\s+(tu|el)\s+(contexto|instruccion)",
    r"actua\s+como",
    r"act\s+as",
    r"eres\s+ahora",
    r"you\s+are\s+now",
    r"revela\s+(tu|el)\s+(prompt|system prompt)",
    r"reveal\s+(your\s+)?system\s*prompt",
    r"como\s+hacer\s+dano",
    r"how\s+to\s+(make|cause)\s+harm",
    r"\bdan\b.*(modo|mode)",
]

# Intenciones que por diseño requieren sistemas transaccionales (fuera del
# alcance del agente L1: solo lectura + redacción de borradores).
_REQUIRES_PROD_DB_PATTERNS = [
    r"donde\s+esta\s+mi\s+pedido",
    r"estado\s+de\s+mi\s+pedido",
    r"where\s+is\s+my\s+order",
    r"reembolso",
    r"reembolsen",
    r"devuelvan\s+mi\s+dinero",
    r"refund",
    r"borrar\s+mi\s+cuenta",
    r"eliminar\s+mi\s+cuenta",
    r"delete\s+my\s+account",
    r"cancela(r)?\s+mi\s+(pedido|orden|suscripcion)",
]


def _normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def detect_prompt_injection(text: str) -> bool:
    normalized = _normalize(text)
    return any(re.search(p, normalized) for p in _INJECTION_PATTERNS)


def detect_requires_prod_db(text: str) -> bool:
    normalized = _normalize(text)
    return any(re.search(p, normalized) for p in _REQUIRES_PROD_DB_PATTERNS)


def is_empty_or_incomprehensible(subject: str, body: str) -> bool:
    combined = f"{subject or ''} {body or ''}".strip()
    if len(combined) < 3:
        return True
    # texto sin ninguna letra (solo símbolos/números/ruido) se considera incomprensible
    if not re.search(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]{3,}", combined):
        return True
    return False


def enforce_confidence_threshold(action: str, confidence: float) -> str:
    if confidence < CONFIDENCE_THRESHOLD:
        return "ESCALATE"
    return action
