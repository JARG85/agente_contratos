"""API Flask del agente de triage de soporte L1.

Ver propuesta_ia.md (spec) y NOTA_ARQUITECTURA.md (decisiones de diseño).
"""
from flask import Flask, jsonify, request

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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
