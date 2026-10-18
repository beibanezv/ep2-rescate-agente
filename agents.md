# agents.md — ep2-rescate-agente (ENTREGABLE EP2)

Repo entregable de la EP2 (ISY0101): el spike `ep2-rescate-andino` ganó el
corte del 18-10 y fue promovido a repo limpio.

- **Dominio:** coordinador de operaciones de búsqueda y rescate andino.
  Datos: `data/ficha-persona.json`, `data/zonas.json`, `data/equipos.json`,
  `data/clima.json` (editable: el evento del acto 2); corpus en `data/corpus/`.
- **Motor:** heredado de `ep2-esqueleto` (loop, memoria, RAG, trace; ver
  `ep2-esqueleto/agents.md` para la API del `AgenteBase`).
- **Dominio:** `tools/rastreo.py`, `agent/rastreo.py`, `main.py --plan`,
  `tests/test_rastreo.py`.
- **Consola visual:** `scripts/generar_consola.py` regenera
  `consola/consola.html` desde los datos reales de `data/` (idempotente).

## Estado (2026-10-18)

- Smoke test completo verificado hoy: ingesta 2/2 MATCH, acto 1 (plan v1 con
  HEL-1+DR-1 en 06:00-12:00) y acto 2 (viento 38-55 km/h → HEL-1 fuera,
  DR-1 solo en Z-5, motivo con regla citada, memoria cita plan v1).
- Tests 10/10.
- Pendiente (pauta): orquestación con framework (LangGraph/CrewAI), evals,
  evidencia final con Groq real, informe 5 págs.

## Reglas de la casa

- Un solo path de Chroma por proceso; `--falso` por defecto (cuota Groq solo
  para evidencia final); commits en español; no subir `.env`, `chroma_db/`,
  `logs/`, `memoria/`.
