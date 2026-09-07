"""Interfaz al modelo de lenguaje: llamada real a la API de Gemini (Google).

`classify_and_draft` llama a `gemini-3.6-flash` con salida estructurada
(`response_schema` + un modelo Pydantic) para clasificar el ticket y
redactar el borrador usando SOLO los artículos de KB ya recuperados por
`agent/kb.py` (el modelo nunca decide qué buscar ni ve nada fuera de eso).

`call_with_retry` es la política real de reintento (backoff exponencial,
máx. 3 intentos) alrededor de la llamada de red. Solo reintenta fallos
transitorios (timeout, rate limit 429, error 5xx del servidor): un error de
configuración (API key inválida, modelo inexistente, request mal formado,
4xx que no sea 429) se deja propagar tal cual — no es algo que un reintento
arregle, y convertirlo en un ESCALATE silencioso escondería un bug real
detrás de una respuesta que parece "normal".
"""
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

# Ruta explícita (no depende del directorio desde el que se corra el proceso).
# No pisa una variable que ya venga exportada en el entorno.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = "gemini-3.6-flash"


class LLMTimeoutError(Exception):
    pass


class LLMUnavailableError(Exception):
    pass


_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            # Error de configuración, no una falla transitoria: no se
            # reintenta, se propaga tal cual para que se note y se corrija.
            raise RuntimeError(
                "Falta GEMINI_API_KEY (o GOOGLE_API_KEY). Crea agente/.env "
                "con GEMINI_API_KEY=tu-clave (ver .env.example)."
            )
        _client = genai.Client(api_key=api_key)
    return _client


def call_with_retry(fn, *args, max_attempts: int = 3, base_delay: float = 0.5, **kwargs):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except (LLMTimeoutError, LLMUnavailableError) as e:
            last_error = e
            if attempt < max_attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_error


class TicketDecision(BaseModel):
    action: str = Field(description="Exactamente 'RESOLVE' o 'ESCALATE'")
    draft_response: str = Field(description="Borrador de respuesta para el cliente, en español, listo para revisión humana")
    confidence_score: float = Field(description="0.0 a 1.0: qué tan seguro estás de que el borrador resuelve el ticket usando SOLO los artículos de KB entregados")


_SYSTEM_PROMPT = (
    "Eres el motor de clasificación de un agente de soporte L1. Recibes un "
    "ticket y los artículos de la base de conocimiento (KB) que ya fueron "
    "recuperados para ese ticket.\n\n"
    "Reglas estrictas:\n"
    "1. Usa ÚNICAMENTE la información de los artículos de KB entregados. "
    "Nunca inventes políticas, precios, plazos ni procedimientos que no "
    "estén ahí, aunque los conozcas de otro contexto.\n"
    "2. Si el ticket no coincide con la KB entregada con seguridad, responde "
    "action=\"ESCALATE\" con confidence_score bajo (< 0.5).\n"
    "3. confidence_score refleja tu seguridad de que el borrador resuelve el "
    "ticket usando solo la KB entregada — no tu conocimiento general.\n"
    "4. Nunca redactes una acción transaccional (reembolsos, cambios de "
    "cuenta, cancelaciones); eso ya se filtra antes de llegar a ti."
)


def classify_and_draft(subject: str, body: str, kb_hits: list[dict]) -> dict:
    if "FORZAR_TIMEOUT_TEST" in (body or ""):
        # Gancho de prueba: simula una caída sostenida de la API sin tocar
        # la red, para que la suite de evaluación pueda probar la política
        # de reintento de forma determinista y sin costo.
        raise LLMTimeoutError("Timeout simulado de la API del LLM (gancho de prueba)")

    client = _get_client()

    kb_context = "\n\n".join(
        f"[{h['id']}] {h['title']} ({h['url']})\n{h['content']}"
        for h in kb_hits
    )
    user_message = (
        f"Asunto del ticket: {subject}\n"
        f"Cuerpo del ticket: {body}\n\n"
        f"Artículos de KB recuperados:\n{kb_context}"
    )

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=TicketDecision,
                temperature=0,
            ),
        )
    except httpx.TimeoutException as e:
        raise LLMTimeoutError(str(e)) from e
    except errors.ServerError as e:
        raise LLMUnavailableError(str(e)) from e
    except errors.ClientError as e:
        if e.code == 429:
            raise LLMUnavailableError(str(e)) from e
        raise  # 400/401/403/404: bug de configuración, no se reintenta

    decision = response.parsed
    if decision is None:
        raise LLMUnavailableError("Gemini no devolvió una respuesta estructurada válida")

    action = decision.action if decision.action in ("RESOLVE", "ESCALATE") else "ESCALATE"
    confidence = max(0.0, min(1.0, float(decision.confidence_score)))

    return {
        "action": action,
        "draft_response": decision.draft_response,
        "confidence_score": confidence,
        "kb_citations": [h["url"] for h in kb_hits] if action == "RESOLVE" else [],
    }
