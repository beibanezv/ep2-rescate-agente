"""Deja el repo en estado limpio para repetir los actos de la demo.

Borra planes publicados, memoria de sesion, trazas y reservas; restaura el
clima base. No toca el corpus ni la coleccion `conocimiento` de Chroma.
"""
import argparse
from pathlib import Path
import shutil

RAIZ = Path(__file__).resolve().parents[1]


def _borrar(base: Path, patron: str) -> int:
    n = 0
    for p in base.glob(patron):
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir-datos", type=Path, default=RAIZ / "data")
    args = parser.parse_args()
    dir_datos = args.dir_datos.resolve()

    planes = _borrar(dir_datos, "planes/plan-v*.json")
    trazas = _borrar(RAIZ, "logs/*.jsonl")
    sesiones = _borrar(RAIZ, "memoria/sesiones.json")
    shutil.copy2(dir_datos / "clima-base.json", dir_datos / "clima.json")
    _limpiar_chroma()
    print(f"Reset: {planes} planes, {trazas} trazas, {sesiones} archivo de sesiones; clima base restaurado.")


if __name__ == "__main__":
    main()
