"""Memoria corto + largo plazo (IE3/IE4): buffer JSON por sesion + coleccion Chroma `memoria`.

Corto plazo: `memoria/sesiones.json` guarda los ultimos turnos de cada sesion
  (consulta, resumen y campos extra del dominio).
Largo plazo: recuperacion semantica sobre la coleccion `memoria` del mismo
  `chroma_db/`, filtrada por sesion.

Sin dependencias nuevas: chromadb + sentence-transformers, ya del motor.
Si la coleccion no existe, se crea vacia y todo devuelve [] (no rompe tests).
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / ".env")
DIR_CHROMA = RAIZ / "chroma_db"
ARCHIVO_SESIONES = RAIZ / "memoria" / "sesiones.json"
MODELO_EMBEDDINGS = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
MAX_TURNOS_SESION = 20
VENTANA_PROMPT = 5


@dataclass
class Recuerdo:
    texto: str
    fuente: str
    score: float | None = None
    metadata: dict = field(default_factory=dict)


class MemoriaAgente:
    """Buffer por sesion + vector store de recuerdos."""

    def __init__(
        self,
        dir_chroma: Path | None = None,
        archivo_sesiones: Path | None = None,
    ):
        self.dir_chroma = dir_chroma or DIR_CHROMA
        self.archivo_sesiones = archivo_sesiones or ARCHIVO_SESIONES
        self._col = None

    def _coleccion(self):
        if self._col is not None:
            return self._col
        from chromadb import PersistentClient
        from chromadb.utils.embedding_functions import (
            SentenceTransformerEmbeddingFunction,
        )

        ef = SentenceTransformerEmbeddingFunction(model_name=MODELO_EMBEDDINGS)
        try:
            self._col = PersistentClient(path=str(self.dir_chroma)).get_or_create_collection(
                "memoria", embedding_function=ef
            )
        except Exception:
            self._col = None
        return self._col

    def _leer_sesiones(self) -> dict:
        if not self.archivo_sesiones.exists():
            return {}
        try:
            return json.loads(self.archivo_sesiones.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _escribir_sesiones(self, datos: dict) -> None:
        self.archivo_sesiones.parent.mkdir(parents=True, exist_ok=True)
        self.archivo_sesiones.write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def historial(self, sesion_id: str, ultimos: int = VENTANA_PROMPT) -> list[dict]:
        if not sesion_id:
            return []
        return self._leer_sesiones().get(sesion_id, [])[-ultimos:]

    def registrar_turno(
        self,
        sesion_id: str,
        consulta: str,
        resumen: str = "",
        extra: dict | None = None,
    ) -> None:
        """Guarda el turno en el buffer (y como recuerdo semantico si hay Chroma)."""
        if not sesion_id:
            return
        turno = {"consulta": consulta, "resumen": resumen, **(extra or {})}
        datos = self._leer_sesiones()
        turnos = datos.get(sesion_id, [])
        turnos.append(turno)
        datos[sesion_id] = turnos[-MAX_TURNOS_SESION:]
        self._escribir_sesiones(datos)

        col = self._coleccion()
        if col is None:
            return
        n = len(datos[sesion_id])
        texto = f"Sesion {sesion_id} turno {n}: {consulta}."
        if resumen:
            texto += f" {resumen}"
        if extra:
            texto += " " + " ".join(f"{k}={v}" for k, v in extra.items() if v)
        try:
            col.upsert(
                ids=[f"{sesion_id}::{n}"],
                documents=[texto],
                metadatas=[{"tipo": "memoria", "sesion_id": sesion_id}],
            )
        except Exception:
            pass

    def recuperar(
        self, consulta: str, sesion_id: str = "", k: int = 2
    ) -> list[Recuerdo]:
        col = self._coleccion()
        if col is None or not consulta:
            return []
        try:
            where = {"sesion_id": sesion_id} if sesion_id else {"tipo": "memoria"}
            r = col.query(
                query_texts=[consulta], n_results=k, where=where,
                include=["documents", "metadatas", "distances"],
            )
            docs = r.get("documents", [[]])[0]
            metas = r.get("metadatas", [[]])[0]
            dists = r.get("distances", [[None] * len(docs)])[0]
        except Exception:
            return []
        recuerdos = []
        for doc, meta, dist in zip(docs, metas, dists):
            recuerdos.append(Recuerdo(
                texto=doc,
                fuente=f"memoria:{meta.get('sesion_id', '?')}",
                score=float(dist) if dist is not None else None,
                metadata=dict(meta),
            ))
        return recuerdos

    def contexto_para_prompt(self, sesion_id: str, ultimos: int = 3) -> str:
        turnos = self.historial(sesion_id, ultimos=ultimos)
        if not turnos:
            return ""
        lineas = []
        for i, t in enumerate(turnos, start=1):
            linea = f"[M{i}] Pedido: {t['consulta']}"
            if t.get("resumen"):
                linea += f" | Resultado: {t['resumen']}"
            extras = [
                f"{k}: {v}" for k, v in t.items()
                if k not in ("consulta", "resumen") and v
            ]
            if extras:
                linea += " | " + ", ".join(extras)
            lineas.append(linea)
        return "HISTORIAL DE LA SESION:\n" + "\n".join(lineas)
