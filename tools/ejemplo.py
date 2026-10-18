"""Tool de escritura de ejemplo (patron IE1): validar -> escribir JSON en data/salidas/.

Clonar por dominio cambiando validaciones y campos: p.ej. abrir ticket, registrar
plan, aislar host. La validacion en el borde (nombre de archivo, contenido no
vacido, tipos) es parte del patron: las tools no confian en el LLM.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DIR_SALIDAS = RAIZ / "data" / "salidas"
REGEX_NOMBRE = re.compile(r"^[a-z0-9-]+$")


def registrar_salida(
    nombre: str, tipo: str, contenido: dict, dir_salidas: Path | None = None
) -> dict:
    """Valida y persiste una salida del agente. Lanza ValueError si no es valida."""
    if not REGEX_NOMBRE.match(nombre or ""):
        raise ValueError("nombre invalido: usa solo minusculas, numeros y guiones")
    if not isinstance(contenido, dict) or not contenido:
        raise ValueError("contenido vacio: se espera un dict con al menos un campo")
    ruta = dir_salidas or DIR_SALIDAS
    ruta.mkdir(parents=True, exist_ok=True)
    salida = {
        "tipo": tipo,
        "creado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **contenido,
    }
    archivo = ruta / f"{nombre}.json"
    archivo.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"archivo": str(archivo), **salida}


def describir_salida(r: dict) -> str:
    return f"Salida registrada: {r['archivo']} (tipo {r['tipo']})"
