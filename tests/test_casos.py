"""Casos seleccionables: cada ficha cambia la prioridad sin tocar el motor."""
from pathlib import Path

from agent.llm_client import ClienteFalso
from agent.memoria import MemoriaAgente
from agent.rastreo import AgenteRastreo
from agent.retriever import Fragmento
from agent.trace import Trazador

RAIZ = Path(__file__).resolve().parents[1]
CASOS = {
    "morado": RAIZ / "data",
    "refugio": RAIZ / "data" / "casos" / "refugio",
    "mirador": RAIZ / "data" / "casos" / "mirador",
}


class RecuperadorFalso:
    def buscar(self, consulta, k=5, filtro=None):
        return [
            Fragmento(
                id="c1",
                texto="Protocolo de busqueda y criterios de prioridad.",
                tipo="documento",
                fuente="protocolo-busqueda",
                score=0.2,
            )
        ]


def _agente(tmp_path, dir_datos, monkeypatch) -> AgenteRastreo:
    memoria = MemoriaAgente(
        dir_chroma=tmp_path / "chroma",
        archivo_sesiones=tmp_path / "sesiones.json",
    )
    monkeypatch.setattr(memoria, "_coleccion", lambda: None)
    return AgenteRastreo(
        llm=ClienteFalso(),
        trazador=Trazador(archivo=tmp_path / "trace.jsonl"),
        memoria=memoria,
        recuperador=RecuperadorFalso(),
        dir_datos=dir_datos,
    )


def test_casos_tienen_los_cinco_json():
    for caso in ("refugio", "mirador"):
        base = RAIZ / "data" / "casos" / caso
        for nombre in (
            "ficha-persona.json",
            "zonas.json",
            "equipos.json",
            "clima.json",
            "clima-base.json",
        ):
            assert (base / nombre).is_file(), f"{caso}: falta {nombre}"


def test_prioridad_cambia_por_caso(tmp_path, monkeypatch):
    prioridades = {
        caso: _agente(tmp_path, base, monkeypatch)._prioridad_zonas()[0]
        for caso, base in CASOS.items()
    }
    assert prioridades["morado"] == "Z-2"
    assert prioridades["refugio"] == "Z-1"
    assert prioridades["mirador"] == "Z-2"
    assert prioridades["morado"] != prioridades["refugio"]
