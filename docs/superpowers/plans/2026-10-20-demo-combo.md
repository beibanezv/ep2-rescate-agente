# Demo Combo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the rescue demo feel like a live decision-support tool: selectable cases, a what-if conditions simulator, and a short consult chat with a per-phase decision ledger.

**Architecture:** Keep deterministic planning in `agent/rastreo.py` and `tools/rastreo.py`. Cases are data directories passed through the existing `AgenteRastreo(dir_datos=...)`. What-if copies the selected case to a temp directory and applies explicit overrides there; tracked JSON is never mutated. The UI only orchestrates existing calls and renders evidence.

**Tech Stack:** Python 3.13, Streamlit, LangGraph, ChromaDB, pytest, `uv`.

**Spec:** User-approved combo in conversation, 2026-10-20. Constraints: EP2 IE1-IE10, no new dependencies, no CrewAI `kickoff`, LLM only narrates/answers, keep existing delivered behavior.

## Global Constraints

- Do not modify `.env`, print keys, or commit generated `chroma_db/`, `logs/`, `memoria/`, `data/reservas/`, or plan files.
- Do not change ecoturismo unless rescue is fully green.
- Keep the current plan-v1 behavior for the Morado case; new cases live under `data/casos/`.
- What-if overrides go to a temp copy, never to tracked `data/*.json`.
- New non-trivial logic gets a failing test first, then minimal implementation.
- Commit messages in Spanish. Keep `master` clean and pushed.

## Review Focus

- A case switch must not show the previous case's plan, climate, or chat.
- What-if must not leave tracked JSON modified, even if the run fails.
- An unavailable HEL-1/K9/DR-1 must disappear from the plan, not just from the narrative.
- A chat follow-up must use the active case and the conditions used for the latest plan.
- Empty plans, missing case files, and an absent published plan must not crash the UI.

---

### Task 1: Selectable rescue cases

**Files:**
- Create: `data/casos/refugio/ficha-persona.json`, `zonas.json`, `equipos.json`, `clima.json`, `clima-base.json`
- Create: `data/casos/mirador/ficha-persona.json`, `zonas.json`, `equipos.json`, `clima.json`, `clima-base.json`
- Modify: `app.py` (case map, case selector, parameterize data helpers)
- Modify: `scripts/reset_demo.py` (optional `--dir-datos`)
- Test: `tests/test_casos.py`

**Interfaces:**
- `CASOS: dict[str, dict]` with `{"nombre": str, "dir": Path}`; ids `morado`, `refugio`, `mirador`.
- `morado` maps to `RAIZ / "data"`; the others map to `RAIZ / "data" / "casos" / <id>`.
- `_franjas(dir_datos: Path | None = None)` and `_planes(dir_datos: Path | None = None)` accept a case directory.
- `reset_demo.py --dir-datos <path>` deletes `<path>/planes/plan-v*.json` and restores `<path>/clima-base.json` to `<path>/clima.json`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_casos.py
def test_casos_tienen_los_cinco_json():
    for caso in ("refugio", "mirador"):
        base = RAIZ / "data" / "casos" / caso
        for nombre in ("ficha-persona.json", "zonas.json", "equipos.json", "clima.json", "clima-base.json"):
            assert (base / nombre).is_file(), f"{caso}: falta {nombre}"

def test_prioridad_cambia_por_caso(tmp_path):
    prioridades = {}
    for caso, dir_datos in _dirs_casos(tmp_path):
        agente = _agente(tmp_path, dir_datos)
        prioridades[caso] = agente._prioridad_zonas()[0]
    assert prioridades["morado"] == "Z-2"
    assert prioridades["refugio"] == "Z-1"
    assert prioridades["mirador"] == "Z-2"
    assert prioridades["morado"] != prioridades["refugio"]
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m pytest -q tests/test_casos.py`
Expected: FAIL because the case files and helpers do not exist.

- [ ] **Step 3: Add case data and UI mapping**

Copy the four data JSON files from `data/` into each new case. Change only `ficha-persona.json`:
- `refugio`: persona `L. Fuentes, 52 años`; last contact at `Z-1` (refugio); route `Z-1` and `Z-5`.
- `mirador`: persona `J. Silva, 28 años`; last contact at `Z-2`; route `Z-2` and `Z-1`.
Keep the same zones/equipment/climate so the comparison is about the report, not hidden data. Copy `clima-base.json` too.

In `app.py`, add `CASOS` and `DIR_DATOS` before the global `FICHA`/`ZONAS`/`EQUIPOS` loads, then load from `DIR_DATOS`. Add a `st.selectbox("Caso activo", ...)` above the inputs. On change, clear `resultado`, `trace`, `plan_actual`, `plan_previo`, `plan_archivo`, `consulta_resultado`, and `chat`, then rerun. Pass `dir_datos=DIR_DATOS` to every `AgenteRastreo(...)` and to `reset_demo.py`.

- [ ] **Step 4: Run GREEN**

Run: `uv run python -m pytest -q tests/test_casos.py tests/test_rastreo.py`
Expected: all pass; the existing Morado plan tests still pass.

- [ ] **Step 5: Commit**

```bash
git add data/casos app.py scripts/reset_demo.py tests/test_casos.py
git commit -m "Agrega casos seleccionables al centro de operaciones"
```

---

### Task 2: What-if conditions simulator

**Files:**
- Create: `tools/escenario.py`
- Modify: `tools/rastreo.py` (`viabilidad_medio` honors `disponible: false`)
- Modify: `agent/rastreo.py` (night phase filters unavailable means)
- Modify: `app.py` (condition controls, temp execution, restore)
- Modify: `scripts/reset_demo.py` (clean temp dirs if used)
- Test: `tests/test_escenario.py`

**Interfaces:**
- `CONDICIONES_BASE = {"viento_kmh": None, "visibilidad_km": None, "hel_1": True, "k9_1": True, "dr_1": True}`
- `preparar_escenario(origen: Path, destino: Path, condiciones: dict) -> Path` copies the five case JSON files, applies overrides to the copy, and returns `destino`.
- `viabilidad_medio(...)` adds `"fuera de servicio"` when `equipo.get("disponible", True)` is false.
- `AgenteRastreo._construir_plan` builds the night means with `viabilidad_medio` and includes only available ones.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_escenario.py
def test_viento_alto_deja_hel_fuera(tmp_path):
    destino = preparar_escenario(RAIZ / "data", tmp_path / "caso", {"viento_kmh": 50})
    assert viabilidad_medio("HEL-1", "Z-2", _franja(destino, "Z-2", "06:00"), destino)["puede"] is False

def test_viento_bajo_permite_hel(tmp_path):
    destino = preparar_escenario(RAIZ / "data", tmp_path / "caso", {"viento_kmh": 20})
    assert viabilidad_medio("HEL-1", "Z-2", _franja(destino, "Z-2", "06:00"), destino)["puede"] is True

def test_k9_no_disponible_sale_de_la_noche(tmp_path):
    destino = preparar_escenario(RAIZ / "data", tmp_path / "caso", {"k9_1": False})
    agente = _agente(tmp_path, destino)
    plan = agente.planificar(1)["plan"]
    noche = [f for f in plan["fases"] if f["franja"].endswith("05:00")]
    assert all("K9-1" not in f["medios"] for f in noche)

def test_preparar_escenario_no_toca_el_origen(tmp_path):
    antes = (RAIZ / "data" / "clima.json").read_text(encoding="utf-8")
    preparar_escenario(RAIZ / "data", tmp_path / "caso", {"viento_kmh": 50})
    assert (RAIZ / "data" / "clima.json").read_text(encoding="utf-8") == antes
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m pytest -q tests/test_escenario.py`
Expected: FAIL with `ModuleNotFoundError: tools.escenario` and unavailable-mean assertions.

- [ ] **Step 3: Implement `tools/escenario.py` and the availability check**

`preparar_escenario` copies `ficha-persona.json`, `zonas.json`, `equipos.json`, `clima.json`, `clima-base.json` (if present), then:
- wind: set `viento_kmh` in every climate franja;
- visibility: set `visibilidad_km` to 12 / 8 / 3 for `"buena"` / `"regular"` / `"mala"`;
- `hel_1`, `k9_1`, `dr_1`: set `disponible` on `HEL-1`, `K9-1`, `DR-1`.

In `viabilidad_medio`, after loading the equipment, append `"fuera de servicio"` when `not equipo.get("disponible", True)`. In `_construir_plan`, replace the hardcoded night means with a list filtered by `viabilidad_medio(m, zid, FRANJA_NOCTURNA, self.dir_datos)["puede"]`.

In `app.py`, add an expander with:
- `st.selectbox("Viento 06–12", [20, 35, 41, 50])`
- `st.selectbox("Visibilidad", ["buena", "regular", "mala"])`
- `st.toggle("HEL-1 disponible", True)`, `st.toggle("K9-1 disponible", True)`, `st.toggle("DR-1 disponible", True)`
- `st.button("Replanificar con condiciones")` and `st.button("Restaurar condiciones")`.

On replan, create a `tempfile.mkdtemp(prefix="rescate-")` copy, call `AgenteRastreo(dir_datos=temp).planificar(2, ...)`, store `dir_ejecucion`, and compare against the base `plan_actual`. On restore, remove the temp dir and clear the override state. Keep `Aplicar viento` as a one-click preset that sets wind 41 and calls the same path.

- [ ] **Step 4: Run GREEN**

Run: `uv run python -m pytest -q tests/test_escenario.py tests/test_rastreo.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/escenario.py tools/rastreo.py agent/rastreo.py app.py scripts/reset_demo.py tests/test_escenario.py
git commit -m "Agrega simulador de condiciones al plan de rescate"
```

---

### Task 3: Consult chat with memory and run badges

**Files:**
- Modify: `agent/agente_base.py` (`RespuestaBase.modelo`)
- Modify: `agent/rastreo.py` (pass model through `consultar`)
- Modify: `app.py` (`chat` list, render history, latency/model/source badge)
- Test: `tests/test_consulta.py` (assert model is present)

**Interfaces:**
- `RespuestaBase` adds `modelo: str = ""`.
- `AgenteBase.procesar` sets `modelo=respuesta.modelo`; the off-domain branch sets `"sin-llm"`.
- `AgenteRastreo.consultar` returns the same `RespuestaBase` with model.
- `app.py` stores `st.session_state["chat"]` as a list of dicts:
  `{"pregunta", "texto", "fuera_de_dominio", "fuentes", "modelo", "ms", "trace"}`.

- [ ] **Step 1: Write the failing test**

```python
def test_consulta_valida_expone_el_modelo(tmp_path):
    agente, _ = _agente(tmp_path)
    r = agente.consultar("que equipos hay disponibles")
    assert r.modelo == "cliente-falso"
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m pytest -q tests/test_consulta.py::test_consulta_valida_expone_el_modelo`
Expected: FAIL with `AttributeError: 'RespuestaBase' object has no attribute 'modelo'`.

- [ ] **Step 3: Implement model pass-through and chat UI**

Add `modelo` to the dataclass and set it in both `procesar` returns. In `_consultar`, measure `time.perf_counter()`, append to `chat`, and keep `consulta_resultado` for backward compatibility. Render the chat as a bordered panel: question in accent, answer in body, `modelo · ms · N fuentes` caption, warning for out-of-domain. Do not clear the chat when publishing a plan; clear it on reset or case switch.

- [ ] **Step 4: Run GREEN**

Run: `uv run python -m pytest -q tests/test_consulta.py tests/test_esqueleto.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent/agente_base.py agent/rastreo.py app.py tests/test_consulta.py
git commit -m "Convierte la consulta en chat con memoria y evidencia"
```

---

### Task 4: Per-phase decision ledger

**Files:**
- Modify: `app.py` (`_porque_html`, render `<details>` in each phase, add a rules footer)
- Test: none (pure HTML render; covered by the UI check)

**Interfaces:**
- `_porque_html(fase: dict, plan: dict, dir_datos: Path, franjas: list[dict]) -> str` returns a `<details class="why">` block.
- It shows priority rank, zone altitude/access/sweep, the phase climate, each mean's `viabilidad_medio` result and rule, and the plan citations.

- [ ] **Step 1: Implement the ledger**

Inside `_plan_html`, after the chips, append `_porque_html(...)`. Add CSS for `.why`, `.why summary`, `.why-body`, `.ledger-rule`. Add a footer `<details>` named `Registro de decisiones` with the priority formula and `plan["citas"]`.

- [ ] **Step 2: Verify**

Run: `uv run python -m py_compile app.py`
Then open `http://127.0.0.1:8501`, publish the plan, and open one `¿Por qué?` per phase. Confirm the rule, data, and citation are visible and no horizontal overflow at 390×844.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "Agrega registro de decisiones por fase"
```

---

### Task 5: Documentation, full verification, push

**Files:**
- Modify: `README.md`, `agents.md`, `guion-presentacion-ep2.md`, root `../AGENTS.md`
- Modify: `docs/` evidence if the demo flow changed

- [ ] **Step 1: Update the demo script**

Add: case switch (`Morado → Refugio`), what-if (`viento 50`, `HEL-1 no`, `K9 no`), and chat follow-ups (`¿por qué no usaron HEL-1?`, `¿y si el viento baja a 20?`). State that the deterministic plan remains in code and the LLM only narrates.

- [ ] **Step 2: Full test run**

Run: `uv run python -m pytest -q`
Expected: all rescue tests pass (19 + new).

- [ ] **Step 3: UI smoke test**

Restart Streamlit on 8501. Check: case selector, plan v1, what-if v2 with changed means, restore, chat with sources/model/latency, off-topic rejection, no console errors, no horizontal overflow.

- [ ] **Step 4: Commit and push**

```bash
git add README.md agents.md app.py tests data/casos tools/escenario.py
git commit -m "Documenta casos, simulador y chat de la demo"
git push origin master
```

- [ ] **Step 5: Reset demo state**

Run `uv run python scripts/reset_demo.py --dir-datos data` and remove any temp scenario dirs. Leave the server on 8501 with `GROQ REAL`.
