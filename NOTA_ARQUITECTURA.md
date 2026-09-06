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
| Costo por invocación (modelo pequeño tipo Haiku, orden de magnitud) | < $0.001 USD |
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
- **Rate limits del proveedor del LLM:** a cientos de tickets/hora un solo
  proveedor sin colas ni backpressure empieza a devolver 429/503. La política
  de reintento con backoff (`agent/llm.py::call_with_retry`) amortigua picos
  cortos, pero a 100x se necesita una cola (p.ej. worker asíncrono +
  cola de mensajes) en vez de procesar el ticket en la misma request HTTP.
- **El servidor de desarrollo de Flask** (`app.run(debug=True)`) no está
  pensado para ese volumen concurrente; en producción iría detrás de un
  servidor WSGI real (gunicorn/uwsgi) con varios workers.
- **Observabilidad:** con volumen alto, sin métricas de tasa de escalado por
  motivo (`reason`) y de confianza promedio, un cambio en el KB o un cambio
  de modelo puede degradar silenciosamente el % de resolución automática.

## Qué queda explícitamente fuera de este prototipo

- Llamada real a un LLM: `agent/llm.py::classify_and_draft` es una
  simulación determinista basada en reglas y en el score de retrieval, para
  que la suite de evaluación sea 100% reproducible sin depender de una API
  externa ni de una API key. La función está aislada exactamente donde iría
  la llamada real, documentado en su docstring.
- Autenticación/autorización de la API Flask (fuera del alcance del
  assessment; en producción iría detrás de un gateway con auth de
  servicio-a-servicio, dado que el "usuario" de este agente es un sistema
  backend, no una persona).
