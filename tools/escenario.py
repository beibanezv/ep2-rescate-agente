"""Escenario what-if: copia un caso y aplica clima/equipos sin tocar los JSON base."""
import json
import shutil
from pathlib import Path

VISIBILIDAD_KM = {"mala": 3, "regular": 7, "buena": 12}
CLAVES_EQUIPO = {
    "HEL-1": "hel_disponible",
    "K9-1": "k9_disponible",
    "DR-1": "dron_operable",
}


def preparar_escenario(
    origen: Path,
    destino: Path,
    condiciones: dict | None = None,
    copiar_planes: bool = False,
) -> Path:
    """Copia el caso a `destino` y aplica viento, visibilidad y equipos fuera de servicio."""
    origen, destino = Path(origen), Path(destino)
    if origen.resolve() == destino.resolve():
        raise ValueError("el escenario no puede sobrescribir el caso original")

    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(origen, destino, ignore=shutil.ignore_patterns("planes"))
    if copiar_planes and (origen / "planes").exists():
        shutil.copytree(origen / "planes", destino / "planes")

    condiciones = condiciones or {}
    viento = condiciones.get("viento_kmh")
    visibilidad = condiciones.get("visibilidad")

    clima = json.loads((destino / "clima.json").read_text(encoding="utf-8"))
    if viento is not None:
        viento = int(viento)
        if not 0 <= viento <= 120:
            raise ValueError(f"viento fuera de rango: {viento}")
        for franja in clima["franjas"]:
            franja["viento_kmh"] = viento
    if visibilidad is not None:
        if visibilidad not in VISIBILIDAD_KM:
            raise ValueError(f"visibilidad invalida: {visibilidad!r}")
        for franja in clima["franjas"]:
            franja["visibilidad_km"] = VISIBILIDAD_KM[visibilidad]
    (destino / "clima.json").write_text(
        json.dumps(clima, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    equipos = json.loads((destino / "equipos.json").read_text(encoding="utf-8"))
    for equipo in equipos["equipos"]:
        clave = CLAVES_EQUIPO.get(equipo["id"])
        if clave in condiciones:
            equipo["disponible"] = bool(condiciones[clave])
    (destino / "equipos.json").write_text(
        json.dumps(equipos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destino
