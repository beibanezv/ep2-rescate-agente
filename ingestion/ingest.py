"""Ingesta RAG del motor: `data/corpus/*.md` -> coleccion 'conocimiento' de ChromaDB.

Los spikes amplian `cargar_documentos()` con sus propias fuentes (JSON de
fichas, alertas, etc.) manteniendo la convencion de metadata por chunk:
    tipo, fuente_id, nombre, chunk_index
`fuente_id` es lo que el agente cita y con lo que vuelve al dato crudo.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
DIR_CORPUS = RAIZ / "data" / "corpus"
DIR_CHROMA = RAIZ / "chroma_db"

MAX_CHARS = 500
OVERLAP = 50


def cargar_documentos() -> list[dict]:
    """Devuelve [{"fuente_id", "nombre", "texto"}, ...]. Ampliar por spike."""
    docs = []
    for p in sorted(DIR_CORPUS.glob("*.md")):
        docs.append({
            "fuente_id": p.stem,
            "nombre": p.stem.replace("-", " ").title(),
            "texto": p.read_text(encoding="utf-8"),
        })
    return docs


def chunk_texto(texto: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP) -> list[str]:
    parrafos = [p.strip() for p in texto.split("\n") if p.strip()]
    chunks: list[str] = []
    actual = ""
    for p in parrafos:
        while len(p) > max_chars:
            if actual:
                chunks.append(actual)
                actual = ""
            chunks.append(p[:max_chars])
            p = p[max_chars - overlap:]
        if not actual:
            actual = p
        elif len(actual) + 1 + len(p) <= max_chars:
            actual = f"{actual}\n{p}"
        else:
            chunks.append(actual)
            actual = p
    if actual:
        chunks.append(actual)
    return chunks


def _embedding_function():
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    modelo = os.getenv(
        "EMBEDDING_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    return SentenceTransformerEmbeddingFunction(model_name=modelo)


def construir_indice() -> tuple[int, int]:
    from chromadb import PersistentClient

    cliente = PersistentClient(path=str(DIR_CHROMA))
    try:
        cliente.delete_collection("conocimiento")
    except Exception:
        pass
    col = cliente.get_or_create_collection(
        "conocimiento", embedding_function=_embedding_function()
    )

    ids: list[str] = []
    documentos: list[str] = []
    metadatas: list[dict] = []
    for d in cargar_documentos():
        for i, chunk in enumerate(chunk_texto(d["texto"])):
            ids.append(f"{d['fuente_id']}::c{i}")
            documentos.append(chunk)
            metadatas.append({
                "tipo": "documento",
                "fuente_id": d["fuente_id"],
                "nombre": d["nombre"],
                "chunk_index": i,
            })
    col.add(ids=ids, documents=documentos, metadatas=metadatas)
    return len(documentos), col.count()


def verificar() -> bool:
    from chromadb import PersistentClient

    col = PersistentClient(path=str(DIR_CHROMA)).get_collection(
        "conocimiento", embedding_function=_embedding_function()
    )
    casos = [
        ("reglas de viento y visibilidad para helicoptero y dron", {"protocolo-busqueda"}),
        ("formula de prioridad de zonas y reglas de desempate", {"criterios-prioridad"}),
    ]
    ok = True
    for consulta, esperados in casos:
        r = col.query(query_texts=[consulta], n_results=1)
        fuente_id = r["metadatas"][0][0].get("fuente_id", "?")
        paso = fuente_id in esperados
        ok = ok and paso
        print(
            f"{'MATCH ' if paso else 'MISS  '} '{consulta}' -> {fuente_id} "
            f"(esperado: {sorted(esperados)})"
        )
    return ok


if __name__ == "__main__":
    load_dotenv()
    chunks, total = construir_indice()
    print(f"Ingesta OK: {chunks} fragmentos indexados (total en coleccion: {total})")
    raise SystemExit(0 if verificar() else 1)
