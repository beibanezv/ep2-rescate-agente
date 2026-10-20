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
- **Interfaz Streamlit:** `app.py` (Centro de Operaciones) con Groq real por
  defecto y toggle determinista explícito; reutiliza `AgenteRastreo.planificar`,
  `scripts/reset_demo.py`, `tools/escenario.py` y el selector de casos.

## Estado (2026-10-20)

- Orquestación LangGraph: `EstadoPlan` + 5 nodos (`contexto`, `calcular`,
  `publicar`, `redactar`, `memorizar`); `planificar()` invoca el grafo.
- Memoria: el nodo `contexto` recupera el plan previo del buffer y llama a
  `memoria.recuperar(consulta, sesion_id)`; traza `memoria_semantica` y agrega
  `memoria-semantica:<sesion>` a las fuentes.
- Tests 27/27 (motor 8 + dominio 6 + consulta 6 + casos 2 + escenario 5;
  incluye flujo completo del grafo, recuperación semántica en contexto, citas
  `[ F1 ]` con espacios, rechazo fuera de dominio sin publicar plan, casos
  intercambiables y what-if).
- Casos intercambiables: `data/casos/refugio/` y `data/casos/mirador/` con
  ficha, zonas, equipos y clima propios; `AgenteRastreo(dir_datos=...)` reusa
  el mismo motor y escribe en el `planes/` del caso.
- What-if: `tools/escenario.py` copia el caso a un temporal, aplica viento,
  visibilidad y disponibilidad de HEL-1/K9-1/DR-1; los JSON del repo no se
  modifican. `viabilidad_medio` respeta `disponible=False`.
- Chat: `app.py` guarda turnos de `consultar()` con pregunta, fuentes, modelo,
  latencia y número de herramientas; cada fase incluye un `<details>` con
  zona, altitud, acceso, barrido, prioridad y restricciones de los medios.
- Consulta libre: `AgenteRastreo.consultar(consulta, sesion_id)` usa `procesar()`
  con RAG + clima/equipos + `plan-publicado` como tool; no publica plan.
  `planificar()` aplica una puerta híbrida (claves de dominio + score > 0.70)
  y rechaza fuera de dominio sin publicar.
- Actos 1 y 2 regenerados en este repo con Groq real (`openai/gpt-oss-120b`):
  plan v1 con HEL-1+DR-1 en 06:00-12:00; acto 2 con viento 41/38 km/h →
  HEL-1 fuera, DR-1 solo en Z-5, motivo con regla citada, memoria semántica y
  de buffer citadas.
- Reset reproducible: `scripts/reset_demo.py --dir-datos <caso>` borra los
  planes del caso, restaura su `clima-base.json` y limpia trazas/memoria;
  `scripts/aplicar_viento.py` sigue disponible para el evento fijo del acto 2.
  La UI usa el simulador what-if sobre un temporal y **Restaurar condiciones**
  para volver al caso base.
- Informe: `docs/informe-ep2.pdf` (4 págs) y `docs/informe-ep2.docx`.
- Evidencia: `docs/salida-acto1.txt`, `docs/salida-acto2.txt` y
  `docs/plan-v2-evidencia.json`.
- Prompt del parte: temperatura 0, `max_tokens=4096` con `reasoning_effort=low`
  y reglas para transcribir el plan publicado sin inventar fases ni medios.

## Reglas de la casa

- Un solo path de Chroma por proceso; el CLI usa Groq real por defecto y
  `--falso` activa el cliente determinista; commits en español; no subir
  `.env`, `chroma_db/`, `logs/`, `memoria/`.
