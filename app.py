"""Centro de operaciones del agente de rescate (Streamlit).

La interfaz no decide nada: muestra el caso, dispara el mismo
`AgenteRastreo.planificar()` que usa el CLI y publica el plan y la traza.
Por defecto usa Groq real; el interruptor "Modo determinista" usa
`ClienteFalso` y queda rotulado en pantalla.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ / ".env")

from agent.llm_client import ClienteFalso, ClienteLangChain
from agent.observabilidad import init_langsmith
from agent.rastreo import AgenteRastreo
from agent.trace import Trazador
from tools.escenario import preparar_escenario

init_langsmith()

st.set_page_config(
    page_title="Centro de Operaciones · El Morado",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CONSULTA_DEFECTO = (
    "excursionista desaparecida en El Morado; ultimo contacto 14:05 en el mirador"
)
SESION_DEFECTO = "caso-morado"

CASOS = {
    "morado": {
        "nombre": "El Morado · M. Torres",
        "dir": RAIZ / "data",
        "consulta": CONSULTA_DEFECTO,
        "sesion": SESION_DEFECTO,
    },
    "refugio": {
        "nombre": "Refugio · L. Fuentes",
        "dir": RAIZ / "data" / "casos" / "refugio",
        "consulta": "excursionista desaparecida en el Refugio El Morado; ultimo contacto 16:20 en el refugio",
        "sesion": "caso-refugio",
    },
    "mirador": {
        "nombre": "Mirador · J. Silva",
        "dir": RAIZ / "data" / "casos" / "mirador",
        "consulta": "excursionista desaparecida en el mirador de la cascada; ultimo contacto 15:10",
        "sesion": "caso-mirador",
    },
}


def _e(valor) -> str:
    return html.escape(str(valor if valor is not None else ""))


def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _limpiar_estado() -> None:
    for clave in (
        "resultado",
        "trace",
        "plan_actual",
        "plan_previo",
        "plan_archivo",
        "consulta_resultado",
        "chat",
        "viento",
        "modo",
        "modelo",
        "escenario",
    ):
        st.session_state.pop(clave, None)
    escenario = st.session_state.pop("dir_escenario", None)
    if escenario:
        shutil.rmtree(escenario, ignore_errors=True)
    caso = CASOS[st.session_state.get("caso_activo", "morado")]
    st.session_state["consulta"] = caso["consulta"]
    st.session_state["sesion"] = caso["sesion"]


CASO_ACTIVO = st.session_state.get("caso_activo", "morado")
DIR_BASE = CASOS[CASO_ACTIVO]["dir"]
DIR_DATOS = Path(st.session_state.get("dir_escenario") or DIR_BASE)
FICHA = _leer_json(DIR_DATOS / "ficha-persona.json", {})
ZONAS = {
    z["id"]: z
    for z in _leer_json(DIR_DATOS / "zonas.json", {"zonas": []})["zonas"]
}
EQUIPOS = {
    e["id"]: e
    for e in _leer_json(DIR_DATOS / "equipos.json", {"equipos": []})["equipos"]
}


def _franjas(dir_datos: Path | None = None) -> list[dict]:
    base = dir_datos or DIR_DATOS
    return _leer_json(base / "clima.json", {"franjas": []}).get("franjas", [])


def _viento_aplicado(franjas: list[dict]) -> bool:
    return any(
        str(f.get("desde", "")).endswith("06:00")
        and int(f.get("viento_kmh", 0)) >= 35
        for f in franjas
    )


def _planes(dir_datos: Path | None = None) -> list[dict]:
    base = dir_datos or DIR_DATOS
    planes = []
    for ruta in sorted((base / "planes").glob("plan-v*.json")):
        try:
            plan = json.loads(ruta.read_text(encoding="utf-8"))
            plan["_archivo"] = ruta.name
            planes.append(plan)
        except Exception:
            continue
    return sorted(planes, key=lambda p: int(p.get("version", 0)))


def _contar_lineas(ruta: str | Path) -> int:
    try:
        return len(Path(ruta).read_text(encoding="utf-8").splitlines())
    except Exception:
        return 0


def _leer_trace(ruta: str | Path, desde: int = 0) -> list[dict]:
    try:
        lineas = Path(ruta).read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    eventos = []
    for linea in lineas[desde:]:
        try:
            eventos.append(json.loads(linea))
        except Exception:
            continue
    return eventos


def _franja(franja: str) -> tuple[str, str]:
    if "23:00" in franja or "22:00" in franja:
        return "NOCHE", "23:00–05:00"
    if "06:00" in franja:
        return "MAÑANA", "06:00–12:00"
    return "TARDE", "12:00–18:00"


def _equipo_chip(equipo_id: str) -> str:
    nombre = EQUIPOS.get(equipo_id, {}).get("nombre", equipo_id)
    return (
        f'<span class="chip chip-medio" title="{_e(nombre)}">'
        f"<b>{_e(equipo_id)}</b> {_e(nombre)}</span>"
    )


def _panel(titulo: str, meta: str, cuerpo: str, clase: str = "") -> str:
    meta_html = f'<span class="panel-meta">{_e(meta)}</span>' if meta else ""
    return (
        f'<section class="panel {clase}">'
        f'<header class="panel-head"><h2>{_e(titulo)}</h2>{meta_html}</header>'
        f'<div class="panel-body">{cuerpo}</div></section>'
    )


def _empty(titulo: str, texto: str) -> str:
    return (
        f'<div class="empty"><p class="empty-title">{_e(titulo)}</p>'
        f"<p>{_e(texto)}</p></div>"
    )


def _ficha_html() -> str:
    filas = [
        ("Persona", FICHA.get("persona", "—")),
        ("Experiencia", FICHA.get("experiencia", "—")),
        ("Equipo", FICHA.get("equipo_declarado", "—")),
        ("Ruta", FICHA.get("ruta_declarada", "—")),
        ("Último contacto", FICHA.get("ultimo_contacto", "—")),
        ("Reporte", FICHA.get("reporte", "—")),
        ("Alertantes", FICHA.get("alertantes", "—")),
    ]
    html_filas = "".join(
        f"<div><dt>{_e(k)}</dt><dd>{_e(v)}</dd></div>" for k, v in filas
    )
    nota = _e(FICHA.get("notas", ""))
    return f'<dl class="data-list">{html_filas}</dl><p class="minor">{nota}</p>'


def _clima_html(franjas: list[dict]) -> str:
    filas = []
    for zona_id in sorted(ZONAS):
        manana = next(
            (
                f
                for f in franjas
                if f.get("zona") == zona_id
                and str(f.get("desde", "")).endswith("06:00")
            ),
            None,
        )
        tarde = next(
            (
                f
                for f in franjas
                if f.get("zona") == zona_id
                and str(f.get("desde", "")).endswith("12:00")
            ),
            None,
        )
        if not manana and not tarde:
            continue
        viento_manana = int((manana or {}).get("viento_kmh", 0))
        viento_tarde = int((tarde or {}).get("viento_kmh", 0))
        vis = (manana or {}).get("visibilidad_km", "—")
        alerta = " alert" if viento_manana >= 35 else ""
        filas.append(
            f'<tr><td class="mono">{_e(zona_id)}</td>'
            f'<td class="mono{alerta}">{viento_manana} km/h</td>'
            f'<td class="mono">{viento_tarde} km/h</td>'
            f'<td class="mono">{_e(vis)} km</td></tr>'
        )
    if not filas:
        return _empty("Sin clima", "No hay franjas de pronóstico disponibles.")
    return (
        '<table class="data-table"><thead><tr><th>Zona</th>'
        "<th>06–12</th><th>12–18</th><th>Vis.</th></tr></thead>"
        f"<tbody>{''.join(filas)}</tbody></table>"
        '<p class="minor">HEL-1 exige viento &lt; 35 km/h y visibilidad &gt; 5 km. '
        "DR-1 exige viento ≤ 40 km/h y luz diurna.</p>"
    )


def _equipos_html() -> str:
    filas = []
    for equipo in EQUIPOS.values():
        filas.append(
            '<div class="equipo">'
            f'<div class="equipo-head"><span class="mono">{_e(equipo.get("id"))}</span>'
            f'<span class="equipo-tipo">{_e(equipo.get("tipo"))}</span></div>'
            f'<p class="equipo-nombre">{_e(equipo.get("nombre"))}</p>'
            f'<p class="equipo-meta">desde {_e(equipo.get("disponible_desde"))} · '
            f'{_e(equipo.get("personas"))} personas · {_e(equipo.get("autonomia_h"))} h</p>'
            f'<p class="equipo-restriccion">{_e(equipo.get("restricciones"))}</p>'
            "</div>"
        )
    return "".join(filas) if filas else _empty("Sin medios", "No hay equipos cargados.")


def _contar_medio(plan: dict, medio: str) -> int:
    return sum(1 for fase in plan.get("fases", []) if medio in fase.get("medios", []))


def _why_html(fase: dict, prioridad: list[str]) -> str:
    zona_id = fase.get("zona", "")
    zona = ZONAS.get(zona_id, {})
    puesto = prioridad.index(zona_id) + 1 if zona_id in prioridad else "—"
    medios = "".join(
        f'<li><b class="mono">{_e(medio)}</b> · {_e(EQUIPOS.get(medio, {}).get("nombre", "equipo"))}: '
        f'{_e(EQUIPOS.get(medio, {}).get("restricciones", "sin restricciones registradas"))}</li>'
        for medio in fase.get("medios", [])
    )
    return (
        '<details class="why"><summary>¿Por qué esta fase?</summary>'
        f'<p><b>{_e(zona.get("nombre", zona_id))}</b> · {_e(zona.get("altitud_m", "—"))} m · '
        f'{_e(zona.get("acceso", "acceso no registrado"))} · barrido {_e(zona.get("barrido_terrestre_h", "—"))} h · '
        f'dron {_e(zona.get("dron", "—"))}. Prioridad #{puesto} '
        f'(probabilidad × facilidad / tiempo de barrido).</p>'
        f'<ul>{medios}</ul>'
        '<p class="why-source">Fuente: zonas.json · equipos.json · protocolo-busqueda §3.</p>'
        "</details>"
    )


def _plan_html(plan: dict | None, previo: dict | None, archivo: str = "") -> str:
    if not plan:
        return _panel(
            "Plan publicado",
            "sin publicar",
            _empty(
                "Todavía no hay un plan",
                "Publica el plan inicial para convertir el reporte en fases, zonas y medios.",
            ),
            "panel-plan",
        )

    version = plan.get("version", "—")
    prioridad = plan.get("prioridad_zonas", [])
    prioridad_html = "".join(
        f'<div class="priority-item"><span class="priority-rank">#{i}</span>'
        f'<b class="mono">{_e(zid)}</b>'
        f'<small>{_e(ZONAS.get(zid, {}).get("nombre", "Zona"))}</small></div>'
        for i, zid in enumerate(prioridad, start=1)
    )

    grupos: dict[str, list[dict]] = {"NOCHE": [], "MAÑANA": [], "TARDE": []}
    for fase in plan.get("fases", []):
        etiqueta, _ = _franja(str(fase.get("franja", "")))
        grupos[etiqueta].append(fase)

    fases_html = []
    for etiqueta, horario in (("NOCHE", "23:00–05:00"), ("MAÑANA", "06:00–12:00"), ("TARDE", "12:00–18:00")):
        fases = grupos[etiqueta]
        if not fases:
            continue
        filas = []
        for fase in fases:
            zona_id = fase.get("zona", "")
            medios = "".join(_equipo_chip(m) for m in fase.get("medios", []))
            filas.append(
                '<div class="phase-row">'
                f'<div class="phase-zone mono">{_e(zona_id)}</div>'
                '<div class="phase-body">'
                f'<p class="phase-objective">{_e(fase.get("objetivo"))}</p>'
                f'<div class="chips">{medios}</div>'
                f"{_why_html(fase, prioridad)}"
                "</div></div>"
            )
        fases_html.append(
            f'<div class="phase-group"><div class="phase-title">'
            f"<span>{etiqueta}</span><small>{horario}</small></div>"
            f"{''.join(filas)}</div>"
        )

    cambio_html = ""
    motivo = plan.get("motivo_cambio") or ""
    if previo:
        deltas = []
        for medio in ("HEL-1", "DR-1", "EQ-1", "EQ-2", "K9-1"):
            antes = _contar_medio(previo, medio)
            ahora = _contar_medio(plan, medio)
            if antes != ahora:
                deltas.append(
                    f'<div class="delta"><span class="mono">{_e(medio)}</span>'
                    f"<b>{antes} → {ahora}</b><small>fases</small></div>"
                )
        cambio_html = (
            '<div class="change">'
            '<div class="change-head"><span>CAMBIOS MATERIALES</span>'
            f"<small>v{_e(previo.get('version'))} → v{_e(version)}</small></div>"
            f'<div class="deltas">{"".join(deltas)}</div>'
            + (f'<p class="change-motive">{_e(motivo)}</p>' if motivo else "")
            + "</div>"
        )
    elif motivo:
        cambio_html = (
            '<div class="change"><div class="change-head">'
            "<span>MOTIVO DEL CAMBIO</span></div>"
            f'<p class="change-motive">{_e(motivo)}</p></div>'
        )

    cuerpo = (
        f'<div class="plan-meta"><span>{_e(archivo or plan.get("_archivo", ""))}</span>'
        f'<span class="plan-state">PUBLICADO</span></div>'
        f'<div class="priority-grid">{prioridad_html}</div>'
        f'<div class="phase-list">{"".join(fases_html)}</div>'
        f"{cambio_html}"
    )
    return _panel("Plan publicado", f"v{version}", cuerpo, "panel-plan")


def _trace_html(resultado: dict | None, trace: list[dict], plan: dict | None) -> str:
    if not resultado:
        return _panel(
            "Trazabilidad",
            _trazador_actual().archivo.name,
            _empty(
                "Esperando una corrida",
                "Cada plan registra contexto, cálculo, publicación, redacción y memoria.",
            ),
        )

    fuentes = resultado.get("fuentes_citadas", [])
    fuentes_html = (
        "".join(f'<span class="chip">{_e(f)}</span>' for f in fuentes)
        if fuentes
        else '<span class="minor">Sin fuentes citadas en el parte.</span>'
    )
    memoria = resultado.get("cito_plan_previo")
    memoria_texto = (
        "El parte cita el plan previo de la sesión."
        if memoria
        else "Sin plan previo citado en esta corrida."
    )
    filas = []
    for evento in trace[-18:]:
        detalle = " · ".join(
            f"{k}={str(v)[:80]}"
            for k, v in evento.items()
            if k not in ("paso", "tipo", "hora_utc")
        )
        filas.append(
            '<div class="trace-row">'
            f'<span class="trace-step">{int(evento.get("paso", 0)):02d}</span>'
            f'<span class="trace-type">{_e(evento.get("tipo"))}</span>'
            f'<span class="trace-detail">{_e(detalle)}</span></div>'
        )
    trace_html = (
        '<div class="trace">' + "".join(filas) + "</div>"
        if filas
        else '<p class="minor">Sin eventos nuevos.</p>'
    )
    citas = (plan or {}).get("citas", [])
    citas_html = "".join(f"<li>{_e(c)}</li>" for c in citas)
    cuerpo = (
        '<div class="status-line"><span class="dot ok"></span>Plan y parte publicados</div>'
        f'<div class="kv"><span>Memoria</span><b>{_e(memoria_texto)}</b></div>'
        f'<div class="kv"><span>Fuentes</span><div class="chips">{fuentes_html}</div></div>'
        '<div class="section-sub">TRAZA DE LA CORRIDA</div>'
        f"{trace_html}"
        '<div class="section-sub">REGLAS CITADAS</div>'
        f'<ul class="citas">{citas_html}</ul>'
    )
    return _panel("Trazabilidad", _trazador_actual().archivo.name, cuerpo)


def _ruta_corta() -> str:
    zonas = list(dict.fromkeys(re.findall(r"Z-\d", FICHA.get("ruta_declarada", ""))))
    return " → ".join(zonas) if zonas else "—"


def _header_html(plan: dict | None, franjas: list[dict], fake: bool) -> str:
    estado = f"PLAN v{plan.get('version')}" if plan else "SIN PLAN"
    modo = "DETERMINISTA · SIN GROQ" if fake else "GROQ REAL"
    modo_clase = "mode-fake" if fake else "mode-real"
    prioridad = plan.get("prioridad_zonas", ["—"])[0] if plan else "sin publicar"
    vientos = [
        int(f.get("viento_kmh", 0))
        for f in franjas
        if str(f.get("desde", "")).endswith("06:00")
    ]
    viento = f"{max(vientos)} km/h máx." if vientos else "sin dato"
    persona = FICHA.get("persona", "—")
    ultimo = FICHA.get("ultimo_contacto", "—")
    return (
        '<div class="topbar">'
        '<div class="brand"><span class="brand-mark">CO</span>'
        "<div><h1>El Morado</h1>"
        f"<p>Caso {_e(FICHA.get('caso', '—'))} · centro de operaciones</p></div></div>"
        f'<div class="top-meta"><span class="dot"></span><span>{_e(estado)}</span>'
        f'<span class="sep"></span><span class="mode {modo_clase}">{_e(modo)}</span></div>'
        "</div>"
        '<div class="hero">'
        '<div class="hero-main"><p class="label">PERSONA DESAPARECIDA</p>'
        f"<h2>{_e(persona)}</h2>"
        f'<p class="hero-copy">Último contacto: {_e(ultimo)}</p></div>'
        '<div class="hero-facts">'
        f'<div><span>RUTA DECLARADA</span><b>{_e(_ruta_corta())}</b></div>'
        f'<div><span>PRIORIDAD</span><b>{_e(prioridad)}</b></div>'
        f'<div><span>VIENTO 06–12</span><b>{_e(viento)}</b></div>'
        "</div></div>"
    )


def _ejecutar_script(nombre: str, args: list[str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / nombre), *(args or [])],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _trazador_actual() -> Trazador:
    caso = st.session_state.get("caso_activo", "morado")
    return Trazador(archivo=RAIZ / "logs" / f"trace-{caso}.jsonl")


def _reset() -> None:
    resultado = _ejecutar_script("reset_demo.py", ["--dir-datos", str(DIR_BASE)])
    if resultado.returncode != 0:
        st.error(f"No se pudo reiniciar: {resultado.stderr.strip()}")
        return
    _limpiar_estado()
    st.rerun()


def _aplicar_escenario(
    viento_kmh: int,
    visibilidad: str,
    hel_disponible: bool,
    k9_disponible: bool,
    dron_operable: bool,
) -> None:
    condiciones = {
        "viento_kmh": viento_kmh,
        "visibilidad": visibilidad,
        "hel_disponible": hel_disponible,
        "k9_disponible": k9_disponible,
        "dron_operable": dron_operable,
    }
    plan = st.session_state.get("plan_actual")
    conservar_v1 = bool(plan and plan.get("version") == 1)
    anterior = st.session_state.pop("dir_escenario", None)
    if anterior:
        shutil.rmtree(anterior, ignore_errors=True)
    destino = Path(tempfile.mkdtemp(prefix=f"rescate-{CASO_ACTIVO}-"))
    try:
        preparar_escenario(
            DIR_BASE,
            destino,
            condiciones,
            copiar_planes=conservar_v1,
        )
    except Exception as exc:
        st.error(f"No se pudo preparar el escenario: {exc}")
        return
    st.session_state["dir_escenario"] = str(destino)
    st.session_state["escenario"] = condiciones
    st.session_state.pop("resultado", None)
    st.session_state.pop("trace", None)
    st.session_state.pop("consulta_resultado", None)
    if not conservar_v1:
        st.session_state.pop("plan_actual", None)
        st.session_state.pop("plan_previo", None)
        st.session_state.pop("plan_archivo", None)
    st.rerun()


def _restaurar_condiciones() -> None:
    _limpiar_estado()
    st.rerun()


def _publicar(version: int, consulta: str, sesion: str, fake: bool) -> None:
    if not fake and not os.getenv("GROQ_API_KEY"):
        st.error("Falta GROQ_API_KEY en .env. Activa el modo determinista o configura la clave.")
        return
    trazador = _trazador_actual()
    previas = _contar_lineas(trazador.archivo)
    llm = ClienteFalso() if fake else ClienteLangChain()
    agente = AgenteRastreo(llm=llm, trazador=trazador, dir_datos=DIR_DATOS)
    try:
        with st.spinner("Calculando prioridad, fases y viabilidad de medios..."):
            resultado = agente.planificar(
                version,
                sesion_id=sesion or None,
                consulta=consulta or CONSULTA_DEFECTO,
            )
    except Exception as exc:
        st.error(f"No se pudo publicar el plan: {exc}")
        return

    if resultado.get("fuera_de_dominio"):
        st.session_state["consulta_resultado"] = {
            "texto": resultado["parte"],
            "fuera_de_dominio": True,
            "fuentes": [],
            "modelo": "ClienteFalso (sin Groq)" if fake else getattr(llm, "modelo", "Groq"),
            "trace": _leer_trace(resultado["archivo_trace"], previas),
        }
        st.rerun()

    previo = next((p for p in _planes(DIR_DATOS) if p.get("version") == version - 1), None)
    plan = resultado["plan"]
    plan["_archivo"] = Path(resultado["archivo"]).name
    st.session_state["resultado"] = resultado
    st.session_state["trace"] = _leer_trace(resultado["archivo_trace"], previas)
    st.session_state["plan_actual"] = plan
    st.session_state["plan_previo"] = previo
    st.session_state["plan_archivo"] = Path(resultado["archivo"]).name
    st.session_state["modo"] = "determinista" if fake else "real"
    st.session_state["modelo"] = (
        "ClienteFalso (sin Groq)" if fake else getattr(llm, "modelo", "Groq")
    )
    st.rerun()


def _consultar(consulta: str, sesion: str, fake: bool) -> None:
    if not fake and not os.getenv("GROQ_API_KEY"):
        st.error("Falta GROQ_API_KEY en .env. Activa el modo determinista o configura la clave.")
        return
    trazador = _trazador_actual()
    previas = _contar_lineas(trazador.archivo)
    llm = ClienteFalso() if fake else ClienteLangChain()
    agente = AgenteRastreo(llm=llm, trazador=trazador, dir_datos=DIR_DATOS)
    inicio = time.perf_counter()
    try:
        with st.spinner("Consultando el corpus y el plan publicado..."):
            r = agente.consultar(consulta, sesion_id=sesion or None)
    except Exception as exc:
        st.error(f"No se pudo responder la consulta: {exc}")
        return
    turno = {
        "pregunta": consulta,
        "texto": r.texto,
        "fuera_de_dominio": r.fuera_de_dominio,
        "fuentes": r.fuentes_citadas,
        "modelo": "ClienteFalso (sin Groq)" if fake else getattr(llm, "modelo", "Groq"),
        "n_herramientas": r.n_herramientas,
        "ms": (time.perf_counter() - inicio) * 1000,
        "trace": _leer_trace(r.archivo_trace, previas),
    }
    st.session_state.setdefault("chat", []).append(turno)
    st.session_state["consulta_resultado"] = turno
    st.rerun()


CSS = r"""
:root {
  --bg: #101416;
  --bg-2: #0c1012;
  --panel: #161b1e;
  --panel-2: #1b2225;
  --input: #111619;
  --line: #2e383b;
  --line-strong: #465357;
  --text: #e7e3d8;
  --muted: #a9b2ae;
  --dim: #7d8a87;
  --accent: #d9a05b;
  --accent-soft: #3a2b1c;
  --ok: #7fb7a8;
  --alert: #e07a6a;
  --mono: "Cascadia Mono", "Consolas", "SFMono-Regular", monospace;
  --sans: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
}
html, body, .stApp, [data-testid="stAppViewContainer"] {
  background: var(--bg);
  color: var(--text);
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"], [data-testid="stAppDeployButton"], [data-testid="stDecoration"] { display: none !important; }
#MainMenu, footer { visibility: hidden; }
.block-container { max-width: 1560px; padding: 1rem 1.5rem 2.5rem; }
* { box-sizing: border-box; }
::selection { background: var(--accent); color: var(--bg); }
* { scrollbar-width: thin; scrollbar-color: var(--line-strong) transparent; }
::-webkit-scrollbar { width: 9px; height: 9px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--line-strong); border: 2px solid var(--bg); border-radius: 6px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
h1, h2, h3, p, li, label, .stMarkdown { font-family: var(--sans); }
h1, h2, h3 { letter-spacing: -0.02em; }
.mono, code { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.topbar {
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  padding: 0.35rem 0 0.9rem; border-bottom: 1px solid var(--line);
}
.brand { display: flex; align-items: center; gap: 0.8rem; }
.brand-mark {
  display: grid; place-items: center; width: 2.3rem; height: 2.3rem;
  border: 1px solid var(--accent); color: var(--accent);
  font: 600 0.72rem/1 var(--mono); letter-spacing: 0.08em;
}
.brand h1 { margin: 0; font-size: 1.55rem; line-height: 1.05; font-weight: 650; }
.brand p { margin: 0.18rem 0 0; color: var(--muted); font-size: 0.76rem; }
.top-meta { display: flex; align-items: center; gap: 0.55rem; color: var(--muted); font-size: 0.7rem; letter-spacing: 0.06em; }
.sep { width: 1px; height: 1rem; background: var(--line); }
.mode { padding: 0.2rem 0.45rem; border: 1px solid var(--line); }
.mode-real { color: var(--ok); border-color: rgba(127,183,168,0.45); }
.mode-fake { color: var(--accent); border-color: rgba(217,160,91,0.45); background: var(--accent-soft); }
.dot { width: 0.45rem; height: 0.45rem; border-radius: 50%; background: var(--accent); display: inline-block; }
.dot.ok { background: var(--ok); }
.hero {
  display: grid; grid-template-columns: 1.35fr 0.9fr; gap: 1.2rem;
  margin: 1rem 0 0.9rem; padding: 1rem 1.1rem; border: 1px solid var(--line);
  background: var(--panel);
}
.label { margin: 0 0 0.25rem; color: var(--accent); font: 600 0.65rem/1.4 var(--mono); letter-spacing: 0.12em; }
.hero h2 { margin: 0; font-size: 1.65rem; font-weight: 620; }
.hero-copy { margin: 0.35rem 0 0; color: var(--muted); font-size: 0.82rem; max-width: 62ch; }
.hero-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; align-self: stretch; }
.hero-facts > div { padding: 0.15rem 0.75rem; border-left: 1px solid var(--line); display: flex; flex-direction: column; justify-content: center; }
.hero-facts span { color: var(--dim); font: 600 0.62rem/1.4 var(--mono); letter-spacing: 0.08em; }
.hero-facts b { margin-top: 0.25rem; color: var(--text); font: 600 0.9rem/1.3 var(--mono); }
.panel { border: 1px solid var(--line); background: var(--panel); margin-bottom: 0.8rem; }
.panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem; padding: 0.6rem 0.8rem; border-bottom: 1px solid var(--line); background: var(--panel-2); }
.panel-head h2 { margin: 0; color: var(--muted); font: 600 0.66rem/1.3 var(--mono); letter-spacing: 0.1em; text-transform: uppercase; }
.panel-meta { color: var(--dim); font: 0.64rem/1.3 var(--mono); text-align: right; }
.panel-body { padding: 0.8rem; }
.minor { color: var(--dim); font-size: 0.72rem; line-height: 1.55; margin: 0.5rem 0 0; }
.data-list { margin: 0; }
.data-list > div { display: grid; grid-template-columns: 5.6rem minmax(0, 1fr); gap: 0.6rem; padding: 0.42rem 0; border-bottom: 1px dashed rgba(70,83,87,0.5); }
.data-list > div:last-child { border-bottom: 0; }
.data-list dt { color: var(--dim); font: 600 0.6rem/1.45 var(--mono); letter-spacing: 0.04em; text-transform: uppercase; padding-top: 0.12rem; }
.data-list dd { margin: 0; color: var(--text); font-size: 0.76rem; line-height: 1.5; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.72rem; }
.data-table th { padding: 0.35rem 0.25rem; color: var(--dim); font: 600 0.6rem/1.3 var(--mono); letter-spacing: 0.04em; text-align: left; text-transform: uppercase; border-bottom: 1px solid var(--line); }
.data-table td { padding: 0.38rem 0.25rem; color: var(--muted); border-bottom: 1px dashed rgba(70,83,87,0.45); }
.data-table tbody tr:last-child td { border-bottom: 0; }
.data-table td:first-child { color: var(--accent); }
.data-table .alert { color: var(--alert); }
.equipo { padding: 0.55rem 0; border-bottom: 1px dashed rgba(70,83,87,0.5); }
.equipo:last-child { border-bottom: 0; padding-bottom: 0; }
.equipo-head { display: flex; align-items: baseline; gap: 0.45rem; }
.equipo-head .mono { color: var(--accent); font-size: 0.72rem; }
.equipo-tipo { color: var(--dim); font: 0.58rem/1.3 var(--mono); letter-spacing: 0.08em; text-transform: uppercase; }
.equipo-nombre { margin: 0.12rem 0 0; color: var(--text); font-size: 0.76rem; font-weight: 600; }
.equipo-meta { margin: 0.12rem 0 0; color: var(--dim); font-size: 0.68rem; }
.equipo-restriccion { margin: 0.14rem 0 0; color: var(--muted); font-size: 0.68rem; line-height: 1.45; }
.plan-meta { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.55rem; color: var(--dim); font-size: 0.66rem; }
.plan-meta .mono { color: var(--accent); font-size: 0.8rem; }
.plan-state { margin-left: auto; color: var(--ok); font: 600 0.58rem/1.3 var(--mono); letter-spacing: 0.08em; }
.priority-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 0.3rem; margin: 0.55rem 0 0.8rem; }
.priority-item { min-width: 0; padding: 0.4rem; border: 1px solid var(--line); background: var(--bg-2); }
.priority-rank { display: block; color: var(--dim); font: 0.58rem/1.2 var(--mono); }
.priority-item b { display: block; margin-top: 0.15rem; color: var(--accent); font-size: 0.78rem; }
.priority-item small { display: block; margin-top: 0.1rem; color: var(--muted); font-size: 0.6rem; line-height: 1.25; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.phase-group { margin-top: 0.7rem; }
.phase-title { display: flex; align-items: baseline; justify-content: space-between; padding-bottom: 0.28rem; border-bottom: 1px solid var(--line); }
.phase-title span { color: var(--muted); font: 600 0.6rem/1.3 var(--mono); letter-spacing: 0.1em; }
.phase-title small { color: var(--dim); font: 0.58rem/1.3 var(--mono); }
.phase-row { display: grid; grid-template-columns: 3.1rem minmax(0, 1fr); gap: 0.55rem; padding: 0.5rem 0; border-bottom: 1px dashed rgba(70,83,87,0.5); }
.phase-row:last-child { border-bottom: 0; }
.phase-zone { color: var(--accent); font-size: 0.72rem; padding-top: 0.08rem; }
.phase-objective { margin: 0; color: var(--text); font-size: 0.72rem; line-height: 1.45; }
.chips { display: flex; flex-wrap: wrap; gap: 0.28rem; margin-top: 0.35rem; }
.why { margin-top: 0.42rem; border-top: 1px dotted rgba(70,83,87,0.55); padding-top: 0.32rem; }
.why summary { cursor: pointer; color: var(--amber); font: 700 0.62rem/1.2 "IBM Plex Mono", monospace; letter-spacing: 0.04em; }
.why p { margin: 0.35rem 0 0; color: var(--muted); font-size: 0.66rem; line-height: 1.45; }
.why ul { margin: 0.3rem 0 0; padding-left: 1rem; color: var(--muted); font-size: 0.66rem; line-height: 1.45; }
.why-source { opacity: 0.75; }
.chip { display: inline-flex; align-items: center; gap: 0.22rem; max-width: 100%; padding: 0.12rem 0.34rem; border: 1px solid var(--line); color: var(--muted); font: 0.6rem/1.35 var(--mono); overflow-wrap: anywhere; }
.chip-medio b { color: var(--accent); font-weight: 600; }
.change { margin-top: 0.8rem; padding: 0.55rem 0.6rem; border: 1px solid rgba(217,160,91,0.38); background: var(--accent-soft); }
.change-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; color: var(--accent); font: 600 0.58rem/1.3 var(--mono); letter-spacing: 0.08em; }
.change-head small { color: var(--muted); font-weight: 400; }
.deltas { display: flex; flex-wrap: wrap; gap: 0.7rem; margin-top: 0.45rem; }
.delta { display: flex; align-items: baseline; gap: 0.3rem; color: var(--muted); font-size: 0.68rem; }
.delta b { color: var(--text); font-family: var(--mono); font-size: 0.7rem; }
.delta small { color: var(--dim); font-size: 0.58rem; }
.change-motive { margin: 0.5rem 0 0; color: var(--muted); font-size: 0.68rem; line-height: 1.5; }
.status-line { display: flex; align-items: center; gap: 0.45rem; color: var(--ok); font: 600 0.66rem/1.4 var(--mono); }
.kv { display: grid; grid-template-columns: 4.7rem minmax(0, 1fr); gap: 0.45rem; padding: 0.38rem 0; border-bottom: 1px dashed rgba(70,83,87,0.5); color: var(--muted); font-size: 0.7rem; line-height: 1.45; }
.kv > span:first-child { color: var(--dim); font: 600 0.6rem/1.45 var(--mono); text-transform: uppercase; }
.kv b { font-weight: 500; }
.section-sub { margin: 0.7rem 0 0.3rem; color: var(--dim); font: 600 0.58rem/1.3 var(--mono); letter-spacing: 0.1em; }
.trace { max-height: 16rem; overflow: auto; border-top: 1px solid var(--line); }
.trace-row { display: grid; grid-template-columns: 1.7rem 6.5rem minmax(0, 1fr); gap: 0.35rem; padding: 0.28rem 0; border-bottom: 1px dashed rgba(70,83,87,0.4); font: 0.6rem/1.4 var(--mono); }
.trace-step { color: var(--dim); }
.trace-type { color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-detail { color: var(--muted); overflow-wrap: anywhere; }
.citas { margin: 0; padding-left: 0.9rem; color: var(--muted); font-size: 0.66rem; line-height: 1.5; }
.citas li { margin-bottom: 0.2rem; }
.empty { padding: 1rem 0.7rem; border: 1px dashed var(--line); text-align: center; }
.empty-title { margin: 0 0 0.25rem; color: var(--muted); font-size: 0.76rem; font-weight: 600; }
.empty p:last-child { margin: 0; color: var(--dim); font-size: 0.68rem; line-height: 1.5; }
.hint { margin: 0.2rem 0 0.7rem; color: var(--dim); font-size: 0.68rem; }
.footer { margin-top: 0.8rem; padding-top: 0.6rem; border-top: 1px solid var(--line); color: var(--dim); font-size: 0.64rem; line-height: 1.5; }
.stButton > button {
  min-height: 2.35rem; border-radius: 3px; border: 1px solid var(--line-strong);
  background: var(--panel); color: var(--text); font: 600 0.72rem/1.2 var(--sans);
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}
.stButton > button:hover { border-color: var(--accent); color: var(--accent); background: var(--panel-2); }
.stButton > button[kind="primary"] { background: var(--accent); border-color: var(--accent); color: #17120c; }
.stButton > button[kind="primary"]:hover { background: #e5b273; border-color: #e5b273; color: #17120c; }
.stButton > button:disabled { opacity: 0.38; }
.stButton > button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
label, .stTextInput label, .stTextArea label, .stToggle label { color: var(--dim) !important; font: 600 0.6rem/1.4 var(--mono) !important; letter-spacing: 0.08em; text-transform: uppercase; }
div[data-baseweb="input"], div[data-baseweb="textarea"] { background: var(--input) !important; border: 1px solid var(--line) !important; border-radius: 2px !important; }
div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within { border-color: var(--accent) !important; }
div[data-baseweb="input"] input, div[data-baseweb="textarea"] textarea { background: transparent !important; color: var(--text) !important; caret-color: var(--accent); }
div[data-baseweb="textarea"] textarea { font-size: 0.76rem; line-height: 1.45; }
[data-testid="stVerticalBlockBorderWrapper"] { background: var(--panel) !important; border: 1px solid var(--line) !important; border-radius: 2px !important; padding: 0.8rem 0.9rem !important; }
[data-testid="stVerticalBlockBorderWrapper"] .stMarkdown p { color: var(--muted); font-size: 0.78rem; line-height: 1.65; }
[data-testid="stVerticalBlockBorderWrapper"] .stMarkdown h3 { color: var(--text); font-size: 0.95rem; }
[data-testid="stSpinner"] { color: var(--muted); }
[data-testid="stAlert"] { border-radius: 2px; }
@media (max-width: 900px) {
  .block-container { padding: 0.8rem 0.9rem 2rem; }
  .topbar { align-items: flex-start; flex-direction: column; }
  .hero { grid-template-columns: 1fr; }
  .hero-facts { grid-template-columns: 1fr 1fr 1fr; margin-top: 0.4rem; }
  .hero-facts > div { padding: 0.4rem 0.5rem; }
  .priority-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .trace-row { grid-template-columns: 1.7rem 5.5rem minmax(0, 1fr); }
}
@media (max-width: 560px) {
  .hero-facts { grid-template-columns: 1fr; }
  .hero-facts > div { border-left: 0; border-top: 1px solid var(--line); }
  .hero-facts > div:first-child { border-top: 0; }
  .priority-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .data-list > div { grid-template-columns: 4.6rem minmax(0, 1fr); }
}
"""

st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

st.selectbox(
    "Caso activo",
    options=list(CASOS),
    format_func=lambda caso: CASOS[caso]["nombre"],
    key="caso_activo",
    on_change=_limpiar_estado,
)

franjas = _franjas(DIR_DATOS)
planes = _planes(DIR_DATOS)
plan_actual = st.session_state.get("plan_actual")
if plan_actual is None:
    plan_actual = planes[-1] if planes else None
    if plan_actual:
        st.session_state["plan_actual"] = plan_actual
plan_previo = st.session_state.get("plan_previo")
if plan_previo is None and plan_actual and plan_actual.get("version", 1) > 1:
    plan_previo = next(
        (p for p in planes if p.get("version") == plan_actual.get("version") - 1),
        None,
    )
archivo_actual = st.session_state.get("plan_archivo") or (
    plan_actual.get("_archivo", "") if plan_actual else ""
)
viento = st.session_state.get("viento", _viento_aplicado(franjas))
resultado = st.session_state.get("resultado")
consulta_resultado = st.session_state.get("consulta_resultado")
trace = st.session_state.get("trace", [])

st.session_state.setdefault("consulta", CONSULTA_DEFECTO)
st.session_state.setdefault("sesion", SESION_DEFECTO)

header_slot = st.empty()

st.markdown('<p class="hint">Secuencia: Reiniciar → Publicar plan inicial → Simulador what-if → Aplicar escenario → Replanificar.</p>', unsafe_allow_html=True)

fila_inputs = st.columns([2.6, 1.25, 1.05])
with fila_inputs[0]:
    consulta = st.text_area("Consulta del operador", height=68, key="consulta")
with fila_inputs[1]:
    sesion = st.text_input("Sesión", key="sesion")
with fila_inputs[2]:
    fake = st.toggle(
        "Determinista",
        value=False,
        help="Usa ClienteFalso: reproduce el plan sin red ni cuota Groq.",
    )
    if fake:
        st.markdown('<span class="chip" style="color:var(--accent);border-color:rgba(217,160,91,.45)">SIN GROQ</span>', unsafe_allow_html=True)

header_slot.markdown(_header_html(plan_actual, franjas, fake), unsafe_allow_html=True)

escenario = st.session_state.get("escenario", {})
with st.expander("Simulador what-if · clima y medios", expanded=False):
    controles = st.columns([1.2, 1, 1, 1, 1])
    viento_sel = controles[0].select_slider(
        "Viento 06–12 (km/h)", options=[20, 35, 41, 50], value=escenario.get("viento_kmh", 20)
    )
    visibilidad_sel = controles[1].selectbox(
        "Visibilidad",
        ["buena", "regular", "mala"],
        index=["buena", "regular", "mala"].index(escenario.get("visibilidad", "buena")),
    )
    hel_sel = controles[2].toggle("HEL-1 disponible", value=escenario.get("hel_disponible", True))
    k9_sel = controles[3].toggle("K9-1 disponible", value=escenario.get("k9_disponible", True))
    dron_sel = controles[4].toggle("DR-1 operable", value=escenario.get("dron_operable", True))
    botones_escenario = st.columns(2)
    boton_escenario = botones_escenario[0].button(
        "Aplicar escenario",
        use_container_width=True,
        help="Copia el caso a un directorio temporal; no modifica los JSON base.",
    )
    boton_restaurar = botones_escenario[1].button(
        "Restaurar condiciones", use_container_width=True
    )

acciones = st.columns([1.15, 1, 1, 1])
with acciones[0]:
    boton_plan = st.button(
        "Publicar plan inicial",
        type="primary",
        use_container_width=True,
        disabled=plan_actual is not None,
    )
with acciones[1]:
    boton_consulta = st.button(
        "Consultar",
        use_container_width=True,
        help="Responde una duda con RAG, clima, equipos y el plan publicado. No publica un plan.",
    )
with acciones[2]:
    boton_replan = st.button(
        "Replanificar",
        use_container_width=True,
        disabled=not (
            plan_actual
            and plan_actual.get("version", 1) == 1
            and (viento or st.session_state.get("dir_escenario"))
        ),
    )
with acciones[3]:
    boton_reset = st.button("Reiniciar escenario", use_container_width=True)

if boton_restaurar:
    _restaurar_condiciones()
if boton_escenario:
    _aplicar_escenario(viento_sel, visibilidad_sel, hel_sel, k9_sel, dron_sel)
if boton_reset:
    _reset()
if boton_plan:
    _publicar(1, consulta, sesion, fake)
if boton_consulta:
    _consultar(consulta or CONSULTA_DEFECTO, sesion, fake)
if boton_replan:
    _publicar(2, "replanifica el operativo por el viento", sesion, fake)

columnas = st.columns([1.05, 1.3, 1.05])
with columnas[0]:
    st.markdown(_panel("Contexto del caso", FICHA.get("caso", "—"), _ficha_html()), unsafe_allow_html=True)
    st.markdown(_panel("Clima simulado", "06–18", _clima_html(franjas)), unsafe_allow_html=True)
    st.markdown(_panel("Medios disponibles", f"{len(EQUIPOS)} medios", _equipos_html()), unsafe_allow_html=True)
with columnas[1]:
    st.markdown(_plan_html(plan_actual, plan_previo, archivo_actual), unsafe_allow_html=True)
with columnas[2]:
    st.markdown(_trace_html(resultado, trace, plan_actual), unsafe_allow_html=True)

chat = st.session_state.get("chat", [])
if chat:
    with st.container(border=True):
        st.markdown(
            f'<div class="panel-head" style="margin:-0.8rem -0.9rem 0.8rem;background:transparent;border-bottom:1px solid var(--line)">'
            f'<h2 style="margin:0;color:var(--muted);font:600 .66rem/1.3 var(--mono);letter-spacing:.1em;text-transform:uppercase">Chat del operador</h2>'
            f'<span class="panel-meta">{len(chat)} turnos · sesión {_e(sesion or "sin sesión")}</span></div>',
            unsafe_allow_html=True,
        )
        for turno in chat:
            st.markdown(f"**Operador ·** {turno['pregunta']}")
            if turno.get("fuera_de_dominio"):
                st.warning(turno["texto"])
            else:
                st.markdown(turno["texto"])
                if turno.get("fuentes"):
                    st.caption("Fuentes: " + ", ".join(turno["fuentes"]))
            st.caption(
                f"modelo: {turno.get('modelo', '—')} · "
                f"{turno.get('ms', 0):.0f} ms · "
                f"{turno.get('n_herramientas', 0)} herramientas"
            )
        if st.button("Limpiar chat", key="limpiar_chat"):
            st.session_state.pop("chat", None)
            st.session_state.pop("consulta_resultado", None)
            st.rerun()

if resultado:
    with st.container(border=True):
        st.markdown(
            f'<div class="panel-head" style="margin:-0.8rem -0.9rem 0.8rem;background:transparent;border-bottom:1px solid var(--line)">'
            f'<h2 style="margin:0;color:var(--muted);font:600 .66rem/1.3 var(--mono);letter-spacing:.1em;text-transform:uppercase">Parte narrativo</h2>'
            f'<span class="panel-meta">modelo: {_e(st.session_state.get("modelo", "—"))}</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(resultado.get("parte", "Sin parte."))
else:
    st.markdown(
        _panel(
            "Parte narrativo",
            "pendiente",
            _empty(
                "El parte se redacta después del plan",
                "El LLM recibe el plan ya validado; no decide zonas ni medios.",
            ),
        ),
        unsafe_allow_html=True,
    )

st.markdown(
    '<p class="footer">Datos del caso y del clima simulados con fines académicos. '
    "El plan se calcula en código determinista; Groq solo redacta el parte. "
    "No apto para operaciones reales.</p>",
    unsafe_allow_html=True,
)
