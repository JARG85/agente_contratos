"""API Flask del agente de triage de soporte L1.

Ver propuesta_ia.md (spec) y NOTA_ARQUITECTURA.md (decisiones de diseño).
"""
import os

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from agent.pipeline import InvalidTicketError, process_ticket

app = Flask(__name__)

# Orígenes de desarrollo local (Vite cae al siguiente puerto libre si el
# anterior está ocupado: 5173 -> 5174 -> ..., de ahí el rango).
_DEV_ORIGINS = [
    r"http://localhost:517\d",
    r"http://127\.0\.0\.1:517\d",
    r"http://localhost:417\d",
    r"http://127\.0\.0\.1:417\d",
]


def _allowed_origins() -> list[str]:
    # En producción se configura con la URL real del frontend desplegado,
    # p.ej. CORS_ORIGINS=https://ft-agente.vercel.app,https://otra-url.com
    # (sin espacios extra; separado por comas). Sin esta variable, se usan
    # los orígenes de desarrollo local de arriba.
    configured = os.environ.get("CORS_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return _DEV_ORIGINS


# Global (no solo /api/*): /health también lo consulta el front para el
# indicador de estado, y no expone nada sensible.
CORS(app, origins=_allowed_origins())


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
    # Un error no manejado aquí (ej. API key de Gemini inválida o
    # ausente) es un bug de configuración, no una falla transitoria del
    # LLM — no lo convertimos en un ESCALATE silencioso, se reporta como
    # error real para que alguien lo note y lo corrija.
    if isinstance(e, HTTPException):
        return e
    app.logger.exception("Error no manejado procesando un ticket")
    return jsonify({"error": "internal_error"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
