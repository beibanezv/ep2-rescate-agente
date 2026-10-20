"""Deja el repo en estado limpio para repetir los actos de la demo.

Borra planes publicados, memoria de sesion, trazas y reservas; restaura el
clima base. No toca el corpus ni la coleccion `conocimiento` de Chroma.
"""
from pathlib import Path
import shutil

RAIZ = Path(__file__).resolve().parents[1]


def _borrar(patron: str) -> int:
    n = 0
    for p in RAIZ.glob(patron):
        if p.is_file():
            p.unlink()
            n += 1
    return n


def _limpiar_chroma() -> None:
    try:
        import chromadb

        cliente = chromadb.PersistentClient(path=str(RAIZ / "chroma_db"))
        cliente.delete_collection("memoria")
    except Exception:
        pass


def main() -> None:
    planes = _borrar("data/planes/plan-v*.json")
    trazas = _borrar("logs/*.jsonl")
    sesiones = _borrar("memoria/sesiones.json")
    shutil.copy2(RAIZ / "data" / "clima-base.json", RAIZ / "data" / "clima.json")
    _limpiar_chroma()
    print(f"Reset: {planes} planes, {trazas} trazas, {sesiones} archivo de sesiones; clima base restaurado.")


if __name__ == "__main__":
    main()
