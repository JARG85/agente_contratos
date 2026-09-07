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
.env.example            # variables requeridas (plantilla, sí se commitea)
.env                    # tus valores reales (NO se commitea, ver .gitignore)
render.yaml             # blueprint de despliegue en Render (ver sección abajo)
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

## Desplegar en Render (gratis)

1. Ve a [dashboard.render.com](https://dashboard.render.com), **New +** →
   **Blueprint**, y selecciona este repo (`agente_contratos`). Render lee
   `render.yaml` solo.
2. Te va a pedir los valores de los env vars marcados `sync: false`:
   - `GEMINI_API_KEY` → tu clave de Google AI Studio.
   - `CORS_ORIGINS` → la URL del frontend ya desplegado en Vercel (ver
     `../agente_ft/README.md`), p.ej. `https://ft-agente.vercel.app`. Si el
     frontend aún no existe, pon un placeholder y actualízalo después desde
     el dashboard (Settings → Environment) — no hace falta re-deployar el
     código, solo el servicio recoge la variable nueva.
3. Deploy. El tier free "duerme" tras ~15 min sin tráfico y tarda unos
   segundos en despertar con la primera petición — normal para una demo, no
   apto para el volumen de la spec (ver `NOTA_ARQUITECTURA.md`).
4. Prueba `https://<tu-servicio>.onrender.com/health` — debe responder
   `{"status": "ok"}`.

**Si el build falla en la versión de Python:** este proyecto usa `.python-version`
(3.14.0, muy reciente) para fijar la versión. Si la imagen de build de
Render todavía no la soporta, cambia `PYTHON_VERSION` en Settings →
Environment del servicio a una versión anterior (3.11/3.12) — el código no
usa nada específico de 3.14.

**Nota sobre el modelo:** `gemini-3.6-flash` en el tier gratuito tiene una
cuota de 20 requests/día (ver hallazgo real en `NOTA_ARQUITECTURA.md`) — para
una demo en vivo con evaluadores puede agotarse rápido; ten un plan B
(capturas de pantalla, o habilitar facturación en el proyecto de Google
Cloud) si vas a demostrarlo varias veces el mismo día.

## Qué NO puede hacer el agente (por diseño, no solo por instrucción)

El código no incluye ninguna función de escritura hacia sistemas externos
(no hay cliente HTTP de salida, no hay `requests`, no hay acceso a base de
datos). El agente solo puede: leer `data/kb.json` y redactar texto. Enviar el
borrador al cliente final requiere una acción humana fuera de este servicio.
