"""Aplica el evento de viento del acto 2 (06:00-12:00) a data/clima.json."""
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CLIMA = RAIZ / "data" / "clima.json"
EVENTO = {
    "Z-1": (48, 3),
    "Z-2": (41, 6),
    "Z-3": (52, 4),
    "Z-4": (55, 4),
    "Z-5": (38, 7),
}

datos = json.loads(CLIMA.read_text(encoding="utf-8"))
for franja in datos["franjas"]:
    if franja["desde"].endswith("06:00"):
        franja["viento_kmh"], franja["visibilidad_km"] = EVENTO[franja["zona"]]
CLIMA.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
print("Evento de viento aplicado a", CLIMA)
