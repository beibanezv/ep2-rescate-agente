"""Modo consulta del operativo: Q&A libre con la misma puerta de dominio.

Sin red: ClienteFalso + recuperador guionado + Chroma de memoria desactivado.
"""
import shutil
from pathlib import Path

from agent.llm_client import ClienteFalso
from agent.memoria import MemoriaAgente
from agent.rastreo import AgenteRastreo
from agent.retriever import Fragmento
from agent.trace import Trazador
from tools.rastreo import publicar_plan

RAIZ = Path(__file__).resolve().parents[1]


class RecuperadorGuion:
    """Devuelve score alto solo para la consulta marcada; el resto es valido."""

    def __init__(self, consulta_alta: str, score_alto: float = 0.9):
        self.consulta_alta = consulta_alta
        self.score_alto = score_alto
        self.llamadas = 0

    def buscar(self, consulta, k=5, filtro=None):
        self.llamadas += 1
        score = self.score_alto if self.consulta_alta in consulta.lower() else 0.2
        return [
            Fragmento(
                id="c1",
                texto="Protocolo de busqueda y criterios de prioridad.",
                tipo="documento",
                fuente="protocolo-busqueda",
                score=score,
            )
        ]


class ClienteCaptura(ClienteFalso):
    def __init__(self):
        super().__init__()
        self.llamadas = 0
        self.usuario = ""

    def completar(self, sistema, usuario):
        self.llamadas += 1
        self.usuario = usuario
        return super().completar(sistema, usuario)


def _datos(tmp_path) -> Path:
    destino = tmp_path / "data"
    shutil.copytree(RAIZ / "data", destino, ignore=shutil.ignore_patterns("planes"))
    return destino


def _agente(tmp_path, dir_datos, recuperador, llm, monkeypatch) -> AgenteRastreo:
    memoria = MemoriaAgente(
        dir_chroma=tmp_path / "chroma",
        archivo_sesiones=tmp_path / "sesiones.json",
    )
    monkeypatch.setattr(memoria, "_coleccion", lambda: None)
    return AgenteRastreo(
        llm=llm,
        trazador=Trazador(archivo=tmp_path / "trace.jsonl"),
        memoria=memoria,
        recuperador=recuperador,
        dir_datos=dir_datos,
    )


def test_consulta_fuera_de_dominio_no_gasta_llm(tmp_path, monkeypatch):
    datos = _datos(tmp_path)
    llm = ClienteCaptura()
    agente = _agente(tmp_path, datos, RecuperadorGuion("francia"), llm, monkeypatch)

    r = agente.consultar("cual es la capital de Francia")

    assert r.fuera_de_dominio is True
    assert llm.llamadas == 0
    assert "Solo puedo ayudar con" in r.texto


def test_consulta_clave_pasa_aunque_score_alto(tmp_path, monkeypatch):
    datos = _datos(tmp_path)
    llm = ClienteCaptura()
    agente = _agente(tmp_path, datos, RecuperadorGuion("m torres"), llm, monkeypatch)

    r = agente.consultar("quien es M Torres")

    assert r.fuera_de_dominio is False
    assert llm.llamadas == 1


def test_consulta_incluye_plan_publicado(tmp_path, monkeypatch):
    datos = _datos(tmp_path)
    base = {
        "franja": "2026-10-17T23:00/2026-10-18T05:00",
        "zona": "Z-2",
        "medios": ["EQ-2"],
        "objetivo": "prueba",
    }
    publicar_plan(1, [base], ["Z-2"], "", [], dir_datos=datos)
    llm = ClienteCaptura()
    agente = _agente(tmp_path, datos, RecuperadorGuion("no-existe"), llm, monkeypatch)

    r = agente.consultar("que dice el plan")

    assert r.fuera_de_dominio is False
    assert llm.llamadas == 1
    assert "PLAN YA PUBLICADO" in llm.usuario
    assert "plan-publicado" in llm.usuario


def test_planificar_fuera_de_dominio_no_publica(tmp_path, monkeypatch):
    datos = _datos(tmp_path)
    agente = _agente(
        tmp_path, datos, RecuperadorGuion("francia"), ClienteFalso(), monkeypatch
    )

    r = agente.planificar(1, consulta="cual es la capital de Francia")

    assert r["fuera_de_dominio"] is True
    assert r["plan"] is None
    assert "Solo puedo ayudar con" in r["parte"]
    assert not (datos / "planes").exists()


def test_planificar_valido_reutiliza_fragmentos(tmp_path, monkeypatch):
    datos = _datos(tmp_path)
    recuperador = RecuperadorGuion("no-existe")
    agente = _agente(tmp_path, datos, recuperador, ClienteFalso(), monkeypatch)

    r = agente.planificar(1, consulta="excursionista desaparecida")

    assert r["fuera_de_dominio"] is False
    assert r["plan"]["version"] == 1
    assert recuperador.llamadas == 1
