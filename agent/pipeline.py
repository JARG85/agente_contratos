"""Orquestación del agente de triage L1.

Orden deliberado (cada paso puede terminar el procesamiento antes de gastar
tokens en el LLM — ver NOTA_ARQUITECTURA.md, sección de coste):

  1. Validar contrato de entrada.
  2. Detectar entrada vacía/incomprensible.
  3. Detectar prompt injection (seguridad, antes que nada más).
  4. Detectar intenciones que requieren sistemas transaccionales (fuera de
     alcance por diseño, sin importar lo que "opine" el LLM).
  5. Tool: buscar en la base de conocimiento (RAG).
  6. LLM: clasificar y redactar borrador, con reintento ante fallo.
  7. Forzar ESCALATE si la confianza queda por debajo del umbral.
"""
from . import guardrails, kb, llm

REQUIRED_FIELDS = ("ticket_id", "subject", "body", "user_tier")


class InvalidTicketError(Exception):
    pass


def _validate_schema(ticket: dict) -> None:
    missing = [f for f in REQUIRED_FIELDS if f not in ticket]
    if missing:
        raise InvalidTicketError(f"Campos requeridos faltantes: {missing}")


def _base_response(ticket: dict) -> dict:
    return {"ticket_id": ticket.get("ticket_id")}


def process_ticket(ticket: dict) -> dict:
    _validate_schema(ticket)

    subject = ticket.get("subject") or ""
    body = ticket.get("body") or ""
    combined_text = f"{subject} {body}"

    response = _base_response(ticket)

    if guardrails.is_empty_or_incomprehensible(subject, body):
        response.update({
            "action": "ESCALATE",
            "draft_response": "El ticket no tiene contenido suficiente para procesarlo. Se solicita clarificación al cliente.",
            "kb_citations": [],
            "confidence_score": 0.0,
            "reason": "input_empty_or_incomprehensible",
        })
        return response

    if guardrails.detect_prompt_injection(combined_text):
        response.update({
            "action": "ESCALATE",
            "draft_response": "Solicitud escalada a soporte N2 para revisión manual.",
            "kb_citations": [],
            "confidence_score": 0.0,
            "reason": "security_alert_prompt_injection",
            "security_alert": True,
        })
        return response

    if guardrails.detect_requires_prod_db(combined_text):
        response.update({
            "action": "ESCALATE",
            "draft_response": (
                "Esta solicitud requiere consultar sistemas transaccionales "
                "(pedidos/pagos) a los que este agente no tiene acceso de "
                "escritura ni de lectura en producción. Se escala a soporte N2."
            ),
            "kb_citations": [],
            "confidence_score": 0.0,
            "reason": "requires_prod_db_out_of_scope",
        })
        return response

    kb_hits = kb.search(combined_text)

    try:
        result = llm.call_with_retry(llm.classify_and_draft, subject, body, kb_hits)
    except (llm.LLMTimeoutError, llm.LLMUnavailableError):
        response.update({
            "action": "ESCALATE",
            "draft_response": "Fallo técnico al procesar el ticket tras reintentos. Marcado para revisión manual.",
            "kb_citations": [],
            "confidence_score": 0.0,
            "reason": "technical_error_llm_unavailable",
            "error_tag": "error_tecnico",
        })
        return response

    final_action = guardrails.enforce_confidence_threshold(
        result["action"], result["confidence_score"]
    )

    response.update({
        "action": final_action,
        "draft_response": result["draft_response"],
        "kb_citations": result["kb_citations"],
        "confidence_score": result["confidence_score"],
        "reason": "low_confidence" if final_action != result["action"] else "ok",
    })
    return response
