# agents.md — ep2-rescate-agente (ENTREGABLE EP2)

Repo entregable de la EP2 (ISY0101): el spike `ep2-rescate-andino` ganó el
corte del 18-10 y fue promovido a repo limpio.

- **Dominio:** coordinador de operaciones de búsqueda y rescate andino.
  Datos: `data/ficha-persona.json`, `data/zonas.json`, `data/equipos.json`,
  `data/clima.json` (editable: el evento del acto 2); corpus en `data/corpus/`.
- **Motor:** heredado de `ep2-esqueleto` (memoria, RAG, trace; ver
  `../ep2-archivo/ep2-esqueleto/agents.md` para la API del `AgenteBase`).
- **Dominio:** `tools/rastreo.py`, `agent/rastreo.py`, `agent/grafo.py`
  (LangGraph), `main.py --plan`, `tests/test_rastreo.py`.
- **Consola visual:** `scripts/generar_consola.py` regenera
  `consola/consola.html` desde los datos reales de `data/` (idempotente).

## Estado (2026-10-19)

- Orquestación LangGraph: `EstadoPlan` + 5 nodos (`contexto`, `calcular`,
  `publicar`, `redactar`, `memorizar`); `planificar()` invoca el grafo.
- Memoria: el nodo `contexto` recupera el plan previo del buffer y llama a
  `memoria.recuperar(consulta, sesion_id)`; traza `memoria_semantica` y agrega
  `memoria-semantica:<sesion>` a las fuentes.
- Tests 14/14 (motor 8 + dominio 6; incluye flujo completo del grafo,
  recuperación semántica en contexto y citas `[ F1 ]` con espacios).
- Actos 1 y 2 regenerados en este repo con Groq real (`openai/gpt-oss-120b`):
  plan v1 con HEL-1+DR-1 en 06:00-12:00; acto 2 con viento 41/38 km/h →
  HEL-1 fuera, DR-1 solo en Z-5, motivo con regla citada, memoria semántica y
  de buffer citadas.
- Reset reproducible: `scripts/reset_demo.py` borra planes/trazas/memoria y
  restaura `data/clima.json` desde `data/clima-base.json`;
  `scripts/aplicar_viento.py` aplica el evento del acto 2.
- Informe: `docs/informe-ep2.pdf` (4 págs) y `docs/informe-ep2.docx`.
- Evidencia: `docs/salida-acto1.txt`, `docs/salida-acto2.txt` y
  `docs/plan-v2-evidencia.json`.
- Prompt del parte: temperatura 0, `max_tokens=4096` con `reasoning_effort=low`
  y reglas para transcribir el plan publicado sin inventar fases ni medios.

## Reglas de la casa

- Un solo path de Chroma por proceso; el CLI usa Groq real por defecto y
  `--falso` activa el cliente determinista; commits en español; no subir
  `.env`, `chroma_db/`, `logs/`, `memoria/`.
