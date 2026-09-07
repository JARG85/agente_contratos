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
  llm.py                # interfaz al LLM real (Gemini) + retry con backoff
data/kb.json            # base de conocimiento de ejemplo
tests/cases.json        # 11 casos de evaluación (incluye adversariales)
tests/run_eval.py       # corre la suite y reporta pass/fail
NOTA_ARQUITECTURA.md    # por qué agente, costo/latencia, qué se rompe a 100x
.env.example            # variable requerida (plantilla, sí se commitea)
.env                    # tu clave real (NO se commitea, ver .gitignore)
```

## Cómo correr

El entorno virtual `asistente/` ya tiene Flask, `google-genai` y
`python-dotenv` instalados.

El agente llama a `gemini-3.6-flash` (Google) para clasificar y redactar.
Necesita una `GEMINI_API_KEY` — gratuita en
[Google AI Studio](https://aistudio.google.com/apikey) — puesta en un
archivo `.env` dentro de esta carpeta (no como variable de entorno exportada
a mano):

```bash
cp .env.example .env
# edita .env y pon: GEMINI_API_KEY=tu-clave-real

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

Salida esperada de `run_eval.py`: **11/11 casos correctos** (exit code 0). Sin
`.env` (o sin `GEMINI_API_KEY` dentro de él), 9/11 pasan igual (son
deterministas y no tocan la API real); los 2 que sí llaman a Gemini (`T01`,
`T02`) fallan con un mensaje claro pidiendo crear `.env`, en vez de romper la
suite completa.

## Qué NO puede hacer el agente (por diseño, no solo por instrucción)

El código no incluye ninguna función de escritura hacia sistemas externos
(no hay cliente HTTP de salida, no hay `requests`, no hay acceso a base de
datos). El agente solo puede: leer `data/kb.json` y redactar texto. Enviar el
borrador al cliente final requiere una acción humana fuera de este servicio.
