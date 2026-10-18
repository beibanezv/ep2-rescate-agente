#!/usr/bin/env python3
"""Genera consola/consola.html del spike SAR a partir de los datos reales de data/.

El HTML es la plantilla: este script reemplaza los bloques entre marcadores
<!-- datos:x --> ... <!-- /datos:x --> con el contenido derivado de
data/ficha-persona.json, data/zonas.json, data/equipos.json, data/clima.json
y data/planes/plan-v*.json (el de versión más alta). Es idempotente.

Uso: uv run python scripts/generar_consola.py
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
CONSOLA = RAIZ / "consola" / "consola.html"

MESES = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
         7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}

CAMPOS_FICHA = [
    ("persona", "Persona"),
    ("experiencia", "Experiencia"),
    ("equipo_declarado", "Equipo declarado"),
    ("ruta_declarada", "Ruta declarada"),
    ("ultimo_contacto", "Último contacto"),
    ("reporte", "Reporte"),
    ("alertantes", "Alertantes"),
    ("notas", "Notas"),
]


def leer_json(ruta: Path):
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


def e(valor) -> str:
    return escape(str(valor), quote=True)


def horas(valor) -> str:
    numero = float(valor)
    texto = str(int(numero)) if numero.is_integer() else str(numero).replace(".", ",")
    return f"{texto} h"


def fecha_legible(marca: str) -> str:
    """'2026-10-17T23:00' -> '17 oct 23:00'."""
    fecha, hora = marca.split("T")
    _, mes, dia = fecha.split("-")
    return f"{int(dia)} {MESES[int(mes)]} {hora}"


def bloque_ficha(ficha: dict) -> str:
    filas = []
    for clave, etiqueta in CAMPOS_FICHA:
        filas.append(f'    <div><dt>{etiqueta}</dt><dd>{e(ficha[clave])}</dd></div>')
    return "\n".join(filas)


def bloque_protocolo(citas: list[str]) -> str:
    items = []
    for cita in citas:
        fuente, _, texto = cita.partition(": ")
        items.append(f'''      <li class="cita"><span class="fuente">{e(fuente)}</span><p>{e(texto)}</p></li>''')
    return "\n".join(items)


def bloque_zonas(plan: dict, zonas: dict, ficha: dict) -> str:
    en_contacto = set(re.findall(r"Z-\d+", ficha["ultimo_contacto"]))
    en_ruta = set(re.findall(r"Z-\d+", ficha["ruta_declarada"]))
    items = []
    for rango, zid in enumerate(plan["prioridad_zonas"], start=1):
        z = zonas[zid]
        etiquetas = []
        if zid in en_contacto:
            etiquetas.append('<span class="tag tag--contacto">Último contacto</span>')
        if zid in en_ruta:
            etiquetas.append('<span class="tag tag--ruta">Ruta declarada</span>')
        fila_etiquetas = ""
        if etiquetas:
            fila_etiquetas = f'\n        <div class="zona__etiquetas">{"".join(etiquetas)}</div>'
        refugios = ", ".join(z["refugios"]) if z["refugios"] else "—"
        items.append(f'''      <li class="zona">
        <div class="zona__cab">
          <span class="zona__rango">{rango}</span>
          <span class="zona__id">{e(zid)}</span>
          <h3>{e(z["nombre"])}</h3>
          <span class="zona__alt mono">{z["altitud_m"]} m</span>
        </div>{fila_etiquetas}
        <dl class="zona__filas">
          <div><dt>Acceso</dt><dd>{e(z["acceso"])}</dd></div>
          <div><dt>Barrido a pie</dt><dd class="mono">{e(horas(z["barrido_terrestre_h"]))}</dd></div>
          <div><dt>Dron</dt><dd>{e(z["dron"])}</dd></div>
          <div><dt>Helicóptero</dt><dd>{e(z["helicoptero"])}</dd></div>
          <div><dt>Refugio</dt><dd>{e(refugios)}</dd></div>
        </dl>
      </li>''')
    return "\n".join(items)


def bloque_fases(plan: dict, zonas: dict, equipos: dict) -> str:
    grupos: dict[str, list[dict]] = {}
    for fase in plan["fases"]:
        grupos.setdefault(fase["franja"], []).append(fase)
    bloques = []
    for franja, fases in grupos.items():
        inicio, fin = franja.split("/")
        hora_inicio = int(inicio.split("T")[1].split(":")[0])
        tipo = "nocturna" if (hora_inicio >= 20 or hora_inicio < 6) else "diurna"
        filas = []
        for fase in fases:
            z = zonas[fase["zona"]]
            chips = " ".join(
                f'<span class="chip chip--medio" title="{e(equipos[m]["nombre"])}">{e(m)}</span>'
                for m in fase["medios"]
            )
            filas.append(f'''    <div class="fase">
      <span class="fase__zona">{e(fase["zona"])}</span>
      <div>
        <h3>{e(z["nombre"])}</h3>
        <p class="fase__objetivo">{e(fase["objetivo"])}</p>
        <div class="fase__medios">{chips}</div>
      </div>
    </div>''')
        bloques.append(f'''  <section class="fase-grupo">
    <h3 class="fase-grupo__titulo">Fase {tipo} — {fecha_legible(inicio)} → {fecha_legible(fin)}</h3>
{chr(10).join(filas)}
  </section>''')
    return "\n".join(bloques)


def bloque_medios(equipos: list[dict]) -> str:
    items = []
    for m in equipos:
        items.append(f'''      <li class="medio">
        <div class="medio__cab"><span>{e(m["id"])}</span><span class="medio__tipo">{e(m["tipo"])}</span></div>
        <h3>{e(m["nombre"])}</h3>
        <p class="medio__meta">{m["personas"]} personas · autonomía {e(horas(m["autonomia_h"]))} · desde {e(m["disponible_desde"])}</p>
        <p class="medio__restr">{e(m["restricciones"])}</p>
      </li>''')
    return "\n".join(items)


def bloque_clima(franjas: list[dict], plan: dict) -> str:
    por_zona: dict[str, list[dict]] = {}
    for f in franjas:
        por_zona.setdefault(f["zona"], []).append(f)
    filas = []
    for zid in plan["prioridad_zonas"]:
        de_zona = [f for f in por_zona.get(zid, [])
                   if f["hasta"].endswith("06:00") or f["hasta"].endswith("12:00")]
        if len(de_zona) != 2:
            continue
        for i, f in enumerate(de_zona):
            franja = "noche" if f["hasta"].endswith("06:00") else "día"
            celda_zona = f'<td class="zona-celda" rowspan="2">{e(zid)}</td>' if i == 0 else ""
            filas.append(f'''        <tr>{celda_zona}
          <td>{franja}</td>
          <td class="mono">{f["viento_kmh"]} km/h</td>
          <td class="mono">{f["visibilidad_km"]} km</td>
          <td class="mono">{f["temp_c"]} °C</td>
        </tr>''')
    return f'''<table class="clima">
        <thead><tr><th>Zona</th><th>Franja</th><th>Viento</th><th>Visib.</th><th>Temp.</th></tr></thead>
        <tbody>
{chr(10).join(filas)}
        </tbody>
      </table>
      <p class="nota">Pronóstico simulado. Solo franjas dentro de la ventana de búsqueda (22:00–06:00 y 06:00–12:00).</p>'''


def bloque_procedencia() -> str:
    archivos = [
        "data/ficha-persona.json",
        "data/zonas.json",
        "data/equipos.json",
        "data/clima.json",
        "data/planes/plan-v1.json",
    ]
    return "\n".join(f'    <li>{e(a)}</li>' for a in archivos)


def inyectar(html: str, bloque: str, contenido: str) -> str:
    patron = re.compile(
        r"(<!-- datos:%s -->).*?(<!-- /datos:%s -->)" % (bloque, bloque), re.S
    )
    nuevo, n = patron.subn(lambda m: m.group(1) + "\n" + contenido + "\n" + m.group(2), html)
    if n == 0:
        raise SystemExit(f"marcador no encontrado en {CONSOLA}: datos:{bloque}")
    return nuevo


def main() -> None:
    ficha = leer_json(DATA / "ficha-persona.json")
    zonas = {z["id"]: z for z in leer_json(DATA / "zonas.json")["zonas"]}
    equipos_lista = leer_json(DATA / "equipos.json")["equipos"]
    equipos = {m["id"]: m for m in equipos_lista}
    franjas = leer_json(DATA / "clima.json")["franjas"]
    planes = sorted((DATA / "planes").glob("plan-v*.json"),
                    key=lambda p: int(re.search(r"plan-v(\d+)", p.name).group(1)))
    plan = leer_json(planes[-1])

    meta_plan = f"plan v{plan['version']} · sin cambios"
    if plan.get("motivo_cambio"):
        meta_plan = f"plan v{plan['version']} · ajuste: {plan['motivo_cambio']}"

    html = CONSOLA.read_text(encoding="utf-8")
    html = inyectar(html, "caso", e(ficha["caso"]))
    html = inyectar(html, "ficha", bloque_ficha(ficha))
    html = inyectar(html, "protocolo", bloque_protocolo(plan["citas"]))
    html = inyectar(html, "zonasmeta",
                    e(f"orden del plan v{plan['version']} · {len(plan['prioridad_zonas'])} zonas"))
    html = inyectar(html, "zonas", bloque_zonas(plan, zonas, ficha))
    html = inyectar(html, "planmeta", e(meta_plan))
    html = inyectar(html, "fases", bloque_fases(plan, zonas, equipos))
    html = inyectar(html, "medios", bloque_medios(equipos_lista))
    html = inyectar(html, "clima", bloque_clima(franjas, plan))
    html = inyectar(html, "procedencia", bloque_procedencia())
    CONSOLA.write_text(html, encoding="utf-8")

    print(f"consola regenerada: {CONSOLA.relative_to(RAIZ)}")
    print(f"  caso {ficha['caso']} · plan v{plan['version']} · {len(plan['fases'])} fases")


if __name__ == "__main__":
    main()
