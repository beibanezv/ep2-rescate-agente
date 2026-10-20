# Brief de datos — Spike rescate andino (coordinador de operaciones)

> Documento histórico del spike original. El entregable evolucionó (LangGraph,
> informe, 14 tests y evidencia real); la fuente vigente es `README.md` y
> `agents.md`. Se conserva como registro de diseño del dominio.

> Spike desechable de la EP2. **Definición de HECHO** (sábado 18-10 noche):
> el momento cumbre de este documento corre end-to-end con `--falso` + el test
> dorado en verde + README actualizado con la salida real.
> Si no corre para esa fecha, el spike muere sin drama.

## 1. La historia (para README e informe)

Central de coordinación de rescate en la cordillera. A las 22:40 entra el
reporte: una excursionista no volvió de su ruta de un día. El coordinador de
operaciones debe convertir un reporte en un **plan de búsqueda por fases**:
leer el perfil de la persona, priorizar zonas según la ruta declarada y el
clima, asignar brigadas, dron y helicóptero dentro de sus ventanas, y
**replanificar en vivo cuando la ventana aérea se pierde** (el viento sube).

El agente hace eso: consulta ficha, zonas, equipos y pronóstico; publica un
plan escrito con fases, asignaciones y fundamentos; y cuando el pronóstico
cambia, publica la versión 2 explicando el motivo del cambio. Nada de esto es
un chatbot: es una mesa de operaciones.

## 2. El empleado y su tarea

- **Rol**: coordinador de operaciones de búsqueda y rescate.
- **Entrada**: reporte del caso (`data/ficha-persona.json`).
- **Contexto**: zonas (`data/zonas.json`), equipos y restricciones
  (`data/equipos.json`), pronóstico por franjas (`data/clima.json`), protocolo
  y criterios de prioridad (corpus RAG).
- **Salida**: plan en `data/planes/plan-v<N>.json`:
  `{version, fases:[{franja, zona, medios[], objetivo}], prioridad_zonas[],
  motivo_cambio, citas[]}`.
- **Guardrail central**: ningún medio se asigna fuera de su ventana (viento,
  visibilidad, luz, autonomía). No se ingresa a zonas técnicas de noche.

## 3. Datos ya presentes en este spike

| Archivo | Contenido |
|---|---|
| `data/ficha-persona.json` | caso 2026-0142: ruta declarada Z-2 → Z-5, sin equipo de altura |
| `data/zonas.json` | 5 zonas (Z-1…Z-5) con acceso, tiempo de barrido, aptitud de medios |
| `data/equipos.json` | 5 medios: brigadas, K9, dron térmico, helicóptero, con restricciones |
| `data/clima.json` | 15 franjas simuladas (5 zonas × 3 franjas); editable: es el evento |
| `data/corpus/protocolo-busqueda.md` | fases, reglas de medios, registro |
| `data/corpus/criterios-prioridad.md` | fórmula de prioridad y desempates |

## 4. Lo que hay que construir (delgado)

### 4.1 Ingesta

`cargar_documentos()` ya indexa `data/corpus/*.md`: solo verificar que la
colección los incluya (2 documentos).

### 4.2 Tools de lectura — `tools/rastreo.py`

- `leer_caso()` → ficha completa.
- `detalle_zonas()` → zonas con tiempos y aptitudes.
- `pronostico(zona=None)` → franjas de clima; por zona o todas.
- `equipos_disponibles()` → medios con sus restricciones.
- `viabilidad_medio(medio, zona, franja)` → calcula si el medio puede operar
  (viento/visibilidad/luz) citando la regla del protocolo.

### 4.3 Tools de escritura — `tools/rastreo.py`

- `publicar_plan(version, fases, prioridad_zonas, motivo_cambio, citas)`
  → valida estructura (franja ISO, zona existente, medios existentes) y escribe
  `data/planes/plan-v<version>.json`.

### 4.4 Agente — `agent/rastreo.py`

Clase `AgenteRastreo(AgenteBase)`:

- `verificaciones_extra(...)`: inyecta clima + equipos como `[T#]`.
- `planificar(version, motivo_cambio=None) -> dict`:
  1. Prioridad: Z-2 (último contacto) → Z-5 y Z-1 (ruta y variantes, barrido
     fácil) → Z-3/Z-4 al final (sin equipo de altura declarado), según la
     fórmula del corpus (citar `[F#]`).
  2. Fase I nocturna: EQ-2 + K9-1 en Z-2/Z-5 (senderos y camino); nunca Z-3/Z-4.
  3. Fase II (06:00-12:00): HEL-1 y DR-1 solo si `viabilidad_medio` lo permite;
     EQ-1 a las variantes de Z-1.
  4. Escribe el plan con las citas de las reglas usadas.
- La decisión de asignación se calcula en código (determinista con `--falso`);
  el LLM redacta el parte narrativo.

### 4.5 CLI

En `main.py` (o `scripts/plan.py`): `--plan` ejecuta la planificación.
`--sesion caso-morado` guarda el turno; en la segunda corrida, la memoria
aporta el plan v1 previo para citar el cambio.

## 5. Momento cumbre — Acto 1 (clima bueno)

```bash
uv sync
uv run python -m ingestion.ingest
uv run python main.py "excursionista desaparecida en El Morado; ultimo contacto 14:05 en el mirador" --plan --falso --sesion caso-morado --pasos
```

Salida esperada (contrato del spike):

1. **Prioridad**: Z-2 primero; Z-5 y Z-1 siguientes; Z-3/Z-4 al final
   ("sin equipo de altura declarado").
2. **Fase I (23:00-05:00 aprox.)**: EQ-2 y K9-1 sobre Z-2 y Z-5; ninguna zona
   técnica; cierre antes del amanecer.
3. **Fase II (06:00-12:00)**: HEL-1 asignado (viento 15-18 km/h, vis 12+),
   DR-1 asignado, EQ-1 en variantes de Z-1.
4. Plan escrito en `data/planes/plan-v1.json` con citas `[F#]`/`[T#]`.

Frase para la demo: *"convierte un reporte en un plan por fases y lo firma con
las reglas del protocolo"*.

## 6. Momento cumbre — Acto 2 (el viento sube)

El operador edita `data/clima.json` y reemplaza **las cinco franjas de
06:00-12:00** por:

| Zona | Viento | Visibilidad |
|---|---|---|
| Z-1 | 48 km/h | 3 km |
| Z-2 | 41 km/h | 6 km |
| Z-3 | 52 km/h | 4 km |
| Z-4 | 55 km/h | 4 km |
| Z-5 | 38 km/h | 7 km |

Correr de nuevo:

```bash
uv run python main.py "replanifica el operativo por el viento" --plan --falso --sesion caso-morado --pasos
```

Contrato del Acto 2:

1. `data/planes/plan-v2.json` **no asigna HEL-1 en 06:00-12:00** (41-55 km/h >
   35) y lo dice con el motivo explícito citando la regla.
2. DR-1 solo donde el viento permite (Z-5, 38 km/h); no en Z-2.
3. Reordena: barrido terrestre reforzado en Z-2/Z-1 durante la mañana.
4. **Extra (no obligatorio)**: proponer reevaluar el helicóptero en la franja
   12:00-18:00 (vientos de la tarde bajo 35), citando el pronóstico.
5. Con `--sesion`, el parte cita el plan v1 previo (memoria).

## 7. Test dorado — `tests/test_rastreo.py`

Con `ClienteFalso` y `tmp_path`:

1. `test_plan_v1_prioriza_ruta_y_usa_helicoptero`: Z-2 antes que Z-3/Z-4;
   HEL-1 presente en 06-12; Fase I sin zonas técnicas.
2. `test_evento_viento_replanifica`: clima del evento → v2 sin HEL-1 en 06-12,
   `motivo_cambio` no vacío, DR-1 solo si viento < 40.
3. `test_fase_nocturna_segura`: ningún plan asigna Z-3/Z-4 antes de 06:00.

## 8. Qué NO hacer

- No evals, no métricas, no informe, no README extenso.
- No CrewAI/LangGraph de grafo complejo; no Streamlit; no LangSmith.
- No tocar la capa genérica del motor salvo `SISTEMA_BASE` y el agente nuevo.
- No inventar medios ni zonas: todo sale de los JSON.

## 9. Cómo verificar

```bash
uv run python -m pytest -q                      # motor (6) + rastreo (3)
uv run python -m ingestion.ingest
uv run python main.py "..." --plan --falso --sesion caso-morado   # acto 1
# (editar clima.json con la tabla del §6)
uv run python main.py "..." --plan --falso --sesion caso-morado   # acto 2
cat data/planes/plan-v2.json
```

Criterio de muerte (sábado 18-10 noche): Acto 1 + Acto 2 según contrato.

## 10. Ética y disclaimer (ponerlo en el README)

Todo es **simulado** con fines académicos: personas, caso y pronóstico
ficticios. El protocolo está inspirado en prácticas reales de montaña, pero
este sistema no es para operaciones reales.
