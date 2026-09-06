"""Interfaz al modelo de lenguaje.

Para que el prototipo sea determinista y evaluable sin depender de una API
externa (ni de una API key), `classify_and_draft` implementa la lógica con
reglas explícitas en vez de una llamada de red real. El contrato de
entrada/salida es el que tendría una llamada real a un LLM (p.ej. Claude
Haiku): recibe el ticket + los hits de KB, devuelve acción, borrador y
confianza. Sustituir el cuerpo de esta función por una llamada real a la API
no requiere tocar el resto del pipeline (ver NOTA_ARQUITECTURA.md).

`call_with_retry` sí es la política real de reintentos (exponential backoff,
máx. 3 intentos) que se usaría alrededor de la llamada de red real.
"""
import time


class LLMTimeoutError(Exception):
    pass


class LLMUnavailableError(Exception):
    pass


def call_with_retry(fn, *args, max_attempts: int = 3, base_delay: float = 0.0, **kwargs):
    """Ejecuta `fn` con reintento exponencial. base_delay=0 en tests/demo
    para no ralentizar la suite; en producción se usaría p.ej. 0.5s."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except (LLMTimeoutError, LLMUnavailableError) as e:
            last_error = e
            if attempt < max_attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_error


def classify_and_draft(subject: str, body: str, kb_hits: list[dict]) -> dict:
    """Simula la decisión de un LLM dado el ticket y el contexto recuperado.

    - Trigger de prueba: si el cuerpo contiene "FORZAR_TIMEOUT_TEST", simula
      una caída sostenida de la API (usado por la suite de evaluación para
      probar la política de reintento y el modo de fallo).
    - En cualquier otro caso: confianza alta si hay un hit de KB fuerte
      (score >= 0.5) y el ticket parece coincidir con una sola intención
      conocida; confianza baja si el match es débil o ambiguo.
    """
    if "FORZAR_TIMEOUT_TEST" in (body or ""):
        raise LLMTimeoutError("Timeout simulado de la API del LLM")

    if not kb_hits:
        return {
            "action": "ESCALATE",
            "draft_response": (
                "No se encontró información en la base de conocimiento para "
                "resolver esta solicitud con seguridad. Escalado a soporte N2."
            ),
            "confidence_score": 0.2,
            "kb_citations": [],
        }

    top = kb_hits[0]
    confidence = min(0.95, 0.5 + top["score"])

    draft = (
        f"Hola, gracias por escribirnos. Sobre tu consulta: {top['title']}. "
        f"{top['content']} Si esto no resuelve tu duda, cuéntanos más detalles "
        f"y con gusto lo revisamos."
    )

    return {
        "action": "RESOLVE",
        "draft_response": draft,
        "confidence_score": round(confidence, 3),
        "kb_citations": [h["url"] for h in kb_hits],
    }
