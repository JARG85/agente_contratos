"""Suite de evaluación del agente de triage.

Ejecuta cada caso de tests/cases.json contra el pipeline (o, para el caso de
contrato inválido, contra la API Flask vía test_client) y compara el
resultado contra lo esperado. Imprime un reporte y termina con exit code != 0
si algún caso falla, para poder engancharlo a CI.

Uso: ./asistente/bin/python tests/run_eval.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.pipeline import InvalidTicketError, process_ticket  # noqa: E402
from app import app  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "cases.json"


def run_case(case: dict) -> tuple[bool, str]:
    expected = case["expected"]

    if "http_error" in expected:
        client = app.test_client()
        resp = client.post("/api/v1/tickets", json=case["input"])
        if resp.status_code == expected["http_error"]:
            return True, f"HTTP {resp.status_code} (esperado)"
        return False, f"HTTP {resp.status_code}, se esperaba {expected['http_error']}"

    try:
        result = process_ticket(case["input"])
    except InvalidTicketError as e:
        return False, f"InvalidTicketError inesperado: {e}"

    checks = []

    if "action" in expected:
        ok = result.get("action") == expected["action"]
        checks.append((ok, f"action={result.get('action')} (esperado {expected['action']})"))

    if "reason" in expected:
        ok = result.get("reason") == expected["reason"]
        checks.append((ok, f"reason={result.get('reason')} (esperado {expected['reason']})"))

    if expected.get("security_alert"):
        ok = result.get("security_alert") is True
        checks.append((ok, f"security_alert={result.get('security_alert')} (esperado True)"))

    if "error_tag" in expected:
        ok = result.get("error_tag") == expected["error_tag"]
        checks.append((ok, f"error_tag={result.get('error_tag')} (esperado {expected['error_tag']})"))

    if expected.get("kb_citations_not_empty"):
        ok = bool(result.get("kb_citations"))
        checks.append((ok, f"kb_citations={result.get('kb_citations')} (se esperaba no vacío)"))

    passed = all(ok for ok, _ in checks)
    detail = "; ".join(msg for _, msg in checks)
    return passed, detail


def main():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        passed, detail = run_case(case)
        results.append((case["id"], case["description"], passed, detail))

    print(f"{'ID':<28} {'PASS':<6} DETALLE")
    print("-" * 100)
    for case_id, description, passed, detail in results:
        mark = "PASS" if passed else "FAIL"
        print(f"{case_id:<28} {mark:<6} {detail}")

    total = len(results)
    passed_count = sum(1 for r in results if r[2])
    print("-" * 100)
    print(f"Resultado: {passed_count}/{total} casos correctos")

    if passed_count != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
