# Agente de Triage y Resolución de Soporte L1

Implementación en Python + Flask del agente descrito en `../propuesta_ia.md`
(spec) y `NOTA_ARQUITECTURA.md` (decisiones de diseño, coste y límites de
escala). Assessment Parte C, variante P3.

## Estructura

```
app.py                 # API Flask (POST /api/v1/tickets, GET /health)
agent/
  pipeline.py           # orquestación del agente (orden de los guardrails y el LLM)
  guardrails.py         # prompt injection, fuera de alcance, umbral de confianza
  kb.py                 # tool de retrieval (RAG) sobre data/kb.json
  llm.py                # interfaz al LLM (simulada, determinista) + retry con backoff
data/kb.json            # base de conocimiento de ejemplo
tests/cases.json        # 11 casos de evaluación (incluye adversariales)
tests/run_eval.py       # corre la suite y reporta pass/fail
NOTA_ARQUITECTURA.md    # por qué agente, costo/latencia, qué se rompe a 100x
```

## Cómo correr

El entorno virtual `asistente/` ya tiene Flask instalado.

```bash
# Levantar la API
./asistente/bin/python app.py
# -> escucha en http://127.0.0.1:5000

# Probar un caso resoluble
curl -s -X POST http://127.0.0.1:5000/api/v1/tickets \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"X1","subject":"clave","body":"olvidé mi contraseña","user_tier":"free"}'

# Correr la suite de evaluación (no requiere el servidor corriendo)
./asistente/bin/python tests/run_eval.py
```

Salida esperada de `run_eval.py`: **11/11 casos correctos** (exit code 0).

## Qué NO puede hacer el agente (por diseño, no solo por instrucción)

El código no incluye ninguna función de escritura hacia sistemas externos
(no hay cliente HTTP de salida, no hay `requests`, no hay acceso a base de
datos). El agente solo puede: leer `data/kb.json` y redactar texto. Enviar el
borrador al cliente final requiere una acción humana fuera de este servicio.
