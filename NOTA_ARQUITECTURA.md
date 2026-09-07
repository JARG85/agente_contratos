# Nota de arquitectura — Agente de Triage y Resolución de Soporte L1

## ¿Por qué agente y no una función determinista?

Una parte del problema **sí** es determinista y se resuelve con reglas fijas, y así
está implementado a propósito (ver `agent/guardrails.py`, ejecutado *antes* de
llamar al modelo):

- Detección de prompt injection.
- Detección de intenciones que requieren sistemas transaccionales (pedidos,
  reembolsos, borrado de cuenta) → estas **nunca** deberían depender de que el
  LLM "decida bien"; se enrutan por regla exacta, sin gastar tokens.
- Umbral de confianza que fuerza `ESCALATE`.

Lo que **no** es determinista, y por eso necesita un modelo de lenguaje, es:
interpretar lenguaje natural libre (variación de redacción, tono, errores de
tipeo) para decidir si el contenido de un ticket coincide semánticamente con
un artículo de la base de conocimiento, y redactar una respuesta natural a
partir de ese contenido. Eso no se puede cubrir con `if/else` sin explotar en
casos de mantenimiento (miles de variantes de la misma pregunta).

Diseño resultante: **capa determinista (barata, auditable, 100% predecible)
hace de guardia perimetral; el LLM solo se invoca para el subconjunto de
casos que de verdad requieren comprensión de lenguaje natural.**

## Coste y latencia estimados

Con el enrutamiento determinista de arriba, no todos los tickets llegan a
invocar el LLM. Estimación aproximada (orden de magnitud, para dimensionar):

| Ítem | Estimado |
|---|---|
| % de tickets resueltos por reglas (injection, out-of-scope, vacíos) sin tocar el LLM | ~20-30% |
| Tokens promedio por invocación al LLM (ticket + KB + instrucciones) | ~800-1.500 tokens |
| Costo por invocación (Gemini 3.6 Flash, orden de magnitud) | < $0.001 USD |
| Volumen esperado (spec) | cientos/hora → ~130.000-250.000 tickets/mes en el escenario alto |
| Costo mensual estimado del LLM | decenas de USD/mes, no miles — coherente con el orden de magnitud usado en B14 ($2.000/mes) si se usa un modelo más grande o context más largo con RAG multi-documento |
| Latencia objetivo (p95, criterio de aceptación de la spec) | < 10s: alcanzable con un modelo pequeño + retrieval local; el retrieval en este prototipo es O(n) sobre keywords y tarda milisegundos con un catálogo de KB pequeño |

La retención de latencia depende más del proveedor del LLM que del pipeline:
retrieval y guardrails son operaciones locales de milisegundos.

## Qué se rompe a 100x el volumen

- **Retrieval por keywords (Jaccard sobre `data/kb.json` en memoria):** funciona
  para decenas de artículos; con miles de artículos de KB se vuelve lento y,
  peor, impreciso (colisiones de palabras clave). Se rompe primero. Solución:
  pasar a un índice vectorial real (embeddings + base vectorial) — el
  contrato de `kb.search()` ya está diseñado para que ese cambio no toque el
  resto del pipeline.
- **Aislamiento multi-tenant de la KB:** el riesgo de "fuga de datos" señalado
  en la spec se vuelve crítico a escala: con más clientes y más documentos,
  la probabilidad de que un artículo mal etiquetado cruce de un tenant a
  otro crece. A 100x hace falta filtrado por tenant en la propia consulta al
  índice, no solo en la carga de datos.
- **Rate limits del proveedor del LLM:** esto no es hipotético — durante las
  pruebas de este mismo prototipo, el tier gratuito de Gemini para
  `gemini-3.6-flash` se agotó con un 429 `RESOURCE_EXHAUSTED` ("limit: 20,
  ... generate_content_free_tier_requests ... per day"). Es decir, el tier
  gratuito se rompe muchísimo antes de "100x": ni siquiera alcanza para un
  día de pruebas manuales, y menos para "cientos de tickets/hora". La
  política de reintento con backoff (`agent/llm.py::call_with_retry`)
  amortigua picos cortos de un 429/503 transitorio, pero contra una cuota
  diaria agotada simplemente reintenta 3 veces en vano y termina en
  `ESCALATE` — que es el comportamiento correcto (degradar a revisión
  humana), pero confirma que producción necesita un tier de pago con cuota
  acorde al volumen, y a más escala, una cola (worker asíncrono + cola de
  mensajes) en vez de procesar el ticket en la misma request HTTP.
- **El servidor de desarrollo de Flask** (`app.run(debug=True)`) no está
  pensado para ese volumen concurrente; en producción iría detrás de un
  servidor WSGI real (gunicorn/uwsgi) con varios workers.
- **Observabilidad:** con volumen alto, sin métricas de tasa de escalado por
  motivo (`reason`) y de confianza promedio, un cambio en el KB o un cambio
  de modelo puede degradar silenciosamente el % de resolución automática.

## Sobre la llamada real al LLM

`agent/llm.py::classify_and_draft` llama de verdad a la API de Gemini
(`gemini-3.6-flash`, Google) con salida estructurada (`response_schema` +
Pydantic), no a una simulación. Esto tiene una consecuencia directa en cómo
se evalúa: los casos de la suite que dependen de una decisión semántica real
(`T01`, `T02`) requieren `GEMINI_API_KEY` configurada y gastan tokens reales
en cada corrida; los que dependen de reglas deterministas (contrato, vacío,
injection, fuera de alcance, sin match en KB) no tocan la red y siguen
siendo 100% reproducibles sin key — ver README, sección "Cómo correr".

Un error de configuración (key ausente/inválida, modelo inexistente) se deja
propagar como error real (ver `app.py::handle_unexpected_error`) en vez de
convertirse en un `ESCALATE` silencioso: esconder un bug de configuración
detrás de una respuesta que parece "normal" es peor que un 500 explícito.

## Qué queda explícitamente fuera de este prototipo

- Autenticación/autorización de la API Flask (fuera del alcance del
  assessment; en producción iría detrás de un gateway con auth de
  servicio-a-servicio, dado que el "usuario" de este agente es un sistema
  backend, no una persona).
