"""Tools de dominio del spike: lectura del caso/zonas/clima/equipos + viabilidad de medios.

Patron IE1 para la escritura: validar en el borde -> persistir JSON en
`data/planes/plan-v<N>.json`. Sin red: todo sale de los JSON de `data/`.
"""
import json
from datetime import datetime, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DIR_DATOS = RAIZ / "data"

# Umbrales del protocolo (§3) para medios aereos; "estricto" = umbral exclusivo.
LIMITES_AEREOS = {
    "HEL-1": {"viento_max_kmh": 35, "viento_estricto": True, "visibilidad_min_km": 5},
    "DR-1": {"viento_max_kmh": 40, "viento_estricto": False, "visibilidad_min_km": 0},
}
REGLAS_AEREAS = {
    "HEL-1": "protocolo-busqueda 3: helicoptero solo con viento < 35 km/h y visibilidad > 5 km, de dia",
    "DR-1": "protocolo-busqueda 3: dron con viento maximo 40 km/h, solo con luz diurna",
}
HORA_DIA_INICIO = time(6, 0)
HORA_DIA_FIN = time(18, 0)
# Con estos datos, sobre esta altura la zona es tecnica (Z-3: 3400 m, Z-4: 3050 m).
ALTITUD_TECNICA_M = 3000


def _leer_json(nombre: str, dir_datos: Path | None = None) -> dict:
    ruta = (dir_datos or DIR_DATOS) / nombre
    return json.loads(ruta.read_text(encoding="utf-8"))


def leer_caso(dir_datos: Path | None = None) -> dict:
    """Ficha completa del caso reportado (`data/ficha-persona.json`)."""
    return _leer_json("ficha-persona.json", dir_datos)


def detalle_zonas(dir_datos: Path | None = None) -> list[dict]:
    """Zonas con acceso, tiempo de barrido y aptitud de cada medio."""
    return _leer_json("zonas.json", dir_datos)["zonas"]


def pronostico(zona: str | None = None, dir_datos: Path | None = None) -> list[dict]:
    """Franjas de clima de una zona o de todas (`data/clima.json`)."""
    franjas = _leer_json("clima.json", dir_datos)["franjas"]
    return [f for f in franjas if zona is None or f["zona"] == zona]


def equipos_disponibles(dir_datos: Path | None = None) -> list[dict]:
    """Medios con personas, autonomia, disponibilidad y restricciones."""
    return _leer_json("equipos.json", dir_datos)["equipos"]


def _intervalo(franja: str) -> tuple[datetime, datetime]:
    partes = str(franja).split("/")
    if len(partes) != 2:
        raise ValueError(f"franja no valida ('desde/hasta' ISO): {franja!r}")
    try:
        inicio, fin = (datetime.fromisoformat(p.strip()) for p in partes)
    except ValueError as e:
        raise ValueError(f"franja no ISO: {franja!r}") from e
    if inicio >= fin:
        raise ValueError(f"franja con inicio >= fin: {franja!r}")
    return inicio, fin


def viabilidad_medio(
    medio: str, zona: str, franja: dict | str, dir_datos: Path | None = None
) -> dict:
    """Calcula si `medio` puede operar en `zona` durante `franja`, citando su regla.

    `franja` es una franja de clima (dict de `pronostico`) o un string
    "desde/hasta" ISO que debe existir en el pronostico de esa zona.
    Devuelve {"medio", "zona", "franja", "puede", "motivos", "regla"}.
    """
    equipos = {e["id"]: e for e in equipos_disponibles(dir_datos)}
    zonas = {z["id"]: z for z in detalle_zonas(dir_datos)}
    if medio not in equipos:
        raise ValueError(f"medio inexistente: {medio!r}")
    if zona not in zonas:
        raise ValueError(f"zona inexistente: {zona!r}")

    if isinstance(franja, dict):
        if franja.get("zona") != zona:
            raise ValueError(f"la franja es de {franja.get('zona')!r}, no de {zona!r}")
        f = franja
    else:
        inicio_buscado, fin_buscado = _intervalo(franja)
        candidatas = [
            x
            for x in pronostico(zona, dir_datos)
            if datetime.fromisoformat(x["desde"]) == inicio_buscado
            and datetime.fromisoformat(x["hasta"]) == fin_buscado
        ]
        if not candidatas:
            raise ValueError(f"sin pronostico para {zona!r} en la franja {franja!r}")
        f = candidatas[0]

    inicio, fin = datetime.fromisoformat(f["desde"]), datetime.fromisoformat(f["hasta"])
    equipo, z = equipos[medio], zonas[zona]
    motivos: list[str] = []
    # shortcut: la autonomia no se checa; las franjas usadas caben en las autonomias
    # declaradas (EQ-2 6 h = franja nocturna, K9 4 h dentro de ella). Revisar si un
    # plan nuevo usa franjas mas largas que la autonomia del medio.

    if inicio.time() < time.fromisoformat(equipo["disponible_desde"]):
        motivos.append(f"no esta disponible antes de {equipo['disponible_desde']}")
    if equipo["tipo"] in ("terrestre", "k9") and z["altitud_m"] >= ALTITUD_TECNICA_M:
        motivos.append(
            f"{zona} es zona tecnica ({z['altitud_m']} m): el {equipo['tipo']} no ingresa sin aclimatacion"
        )

    limites = LIMITES_AEREOS.get(medio)
    if limites:
        if inicio.time() < HORA_DIA_INICIO or fin.time() > HORA_DIA_FIN:
            motivos.append("solo opera con luz diurna (06:00-18:00)")
        viento = int(f["viento_kmh"])
        vis = float(f["visibilidad_km"])
        if limites["viento_estricto"]:
            if viento >= limites["viento_max_kmh"]:
                motivos.append(f"viento {viento} km/h >= {limites['viento_max_kmh']} km/h")
        elif viento > limites["viento_max_kmh"]:
            motivos.append(f"viento {viento} km/h > {limites['viento_max_kmh']} km/h")
        if limites["visibilidad_min_km"] and vis <= limites["visibilidad_min_km"]:
            motivos.append(f"visibilidad {vis} km <= {limites['visibilidad_min_km']} km")

    return {
        "medio": medio,
        "zona": zona,
        "franja": f"{f['desde']}/{f['hasta']}",
        "puede": not motivos,
        "motivos": motivos,
        "regla": REGLAS_AEREAS.get(medio) or f"equipos.json: {equipo['restricciones']}",
    }


def publicar_plan(
    version: int,
    fases: list[dict],
    prioridad_zonas: list[str],
    motivo_cambio: str | None = None,
    citas: list[str] | None = None,
    dir_datos: Path | None = None,
) -> dict:
    """Valida (franja ISO, zona y medios existentes) y escribe `data/planes/plan-v<version>.json`.

    Las tools no confian en el LLM: cualquier estructura invalida lanza ValueError.
    """
    if not isinstance(version, int) or version < 1:
        raise ValueError(f"version invalida: {version!r} (entero >= 1)")
    zonas = {z["id"] for z in detalle_zonas(dir_datos)}
    medios = {e["id"] for e in equipos_disponibles(dir_datos)}
    if not isinstance(fases, list) or not fases:
        raise ValueError("fases vacio: se espera al menos una fase")
    for i, fase in enumerate(fases, start=1):
        if not isinstance(fase, dict):
            raise ValueError(f"fase {i} no es un dict")
        if fase.get("zona") not in zonas:
            raise ValueError(f"fase {i}: zona inexistente {fase.get('zona')!r}")
        if not fase.get("objetivo"):
            raise ValueError(f"fase {i}: falta objetivo")
        fase_medios = fase.get("medios")
        if not isinstance(fase_medios, list) or not fase_medios:
            raise ValueError(f"fase {i}: medios vacio")
        for medio in fase_medios:
            if medio not in medios:
                raise ValueError(f"fase {i}: medio inexistente {medio!r}")
        _intervalo(fase.get("franja"))  # franja ISO 'desde/hasta'
    if not isinstance(prioridad_zonas, list) or not prioridad_zonas:
        raise ValueError("prioridad_zonas vacia")
    for zid in prioridad_zonas:
        if zid not in zonas:
            raise ValueError(f"prioridad_zonas: zona inexistente {zid!r}")

    plan = {
        "version": version,
        "fases": fases,
        "prioridad_zonas": prioridad_zonas,
        "motivo_cambio": motivo_cambio or "",
        "citas": list(citas or []),
    }
    ruta = (dir_datos or DIR_DATOS) / "planes"
    ruta.mkdir(parents=True, exist_ok=True)
    archivo = ruta / f"plan-v{version}.json"
    archivo.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"archivo": str(archivo), **plan}
