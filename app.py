"""API Flask del agente de triage de soporte L1.

Ver propuesta_ia.md (spec) y NOTA_ARQUITECTURA.md (decisiones de diseño).
"""
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from agent.pipeline import InvalidTicketError, process_ticket

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/v1/tickets")
def handle_ticket():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "El body debe ser JSON válido"}), 400

    try:
        result = process_ticket(payload)
    except InvalidTicketError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(result), 200


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    # Un error no manejado aquí (ej. API key de Anthropic inválida o
    # ausente) es un bug de configuración, no una falla transitoria del
    # LLM — no lo convertimos en un ESCALATE silencioso, se reporta como
    # error real para que alguien lo note y lo corrija.
    if isinstance(e, HTTPException):
        return e
    app.logger.exception("Error no manejado procesando un ticket")
    return jsonify({"error": "internal_error"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
