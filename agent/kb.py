"""Tool: búsqueda semántica (simplificada) sobre la base de conocimiento.

Usa solapamiento de palabras clave normalizadas en lugar de embeddings para que
el prototipo sea determinista y no dependa de una API externa. El contrato de
salida (lista de hits con score) es el mismo que tendría un retriever vectorial
real, así que sustituir esta implementación no cambia el resto del pipeline.
"""
import json
import re
import unicodedata
from pathlib import Path

KB_PATH = Path(__file__).resolve().parent.parent / "data" / "kb.json"

_STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "un", "una", "y", "o", "que",
    "en", "por", "para", "mi", "me", "tu", "se", "no", "es", "con", "a",
    "como", "cómo", "porque", "por qué",
}


def _normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


def _tokenize(text: str) -> set[str]:
    text = _normalize(text)
    tokens = re.findall(r"[a-z0-9]+", text)
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 2}


def load_kb() -> list[dict]:
    with open(KB_PATH, encoding="utf-8") as f:
        return json.load(f)


_KB_CACHE = None


def _kb() -> list[dict]:
    global _KB_CACHE
    if _KB_CACHE is None:
        _KB_CACHE = load_kb()
    return _KB_CACHE


def search(query_text: str, top_k: int = 2, min_score: float = 0.15) -> list[dict]:
    """Tool de retrieval. Devuelve hits con score de solapamiento [0,1].

    score = |tokens_query ∩ tokens_articulo| / |tokens_query ∪ tokens_articulo_relevantes|
    (Jaccard sobre keywords del artículo, para mantenerlo barato y explicable.)
    """
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return []

    hits = []
    for article in _kb():
        article_tokens = set()
        for kw in article["keywords"]:
            article_tokens |= _tokenize(kw)

        if not article_tokens:
            continue

        overlap = query_tokens & article_tokens
        if not overlap:
            continue

        score = len(overlap) / len(query_tokens | overlap)
        if score >= min_score:
            hits.append({
                "id": article["id"],
                "url": article["url"],
                "title": article["title"],
                "category": article["category"],
                "content": article["content"],
                "score": round(score, 3),
            })

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]
