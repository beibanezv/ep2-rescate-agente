"""Tests del simulador what-if: copia temporal, clima y equipos fuera de servicio."""
import json
from pathlib import Path

from agent.llm_client import ClienteFalso
from agent.memoria import MemoriaAgente
from agent.rastreo import AgenteRastreo
from agent.retriever import Fragmento
from agent.trace import Trazador
from tools.escenario import preparar_escenario
from tools.rastreo import viabilidad_medio

RAIZ = Path(__file__).resolve().parents[1]


class RecuperadorFalso:
    def buscar(self, consulta, k=5, filtro=None):
        return [
            Fragmento(
                id="c1",
                texto="Plan por fases y prioridad de zonas.",
                tipo="documento",
                fuente="protocolo-busqueda",
                score=0.2,
            )
        ]


def _agente(tmp_path, dir_datos) -> AgenteRastreo:
    memoria = MemoriaAgente(
        dir_chroma=tmp_path / "chroma",
        archivo_sesiones=tmp_path / "sesiones.json",
    )
    memoria._coleccion = lambda: None
    return AgenteRastreo(
        llm=ClienteFalso(),
        trazador=Trazador(archivo=tmp_path / "trace.jsonl"),
        memoria=memoria,
        recuperador=RecuperadorFalso(),
        dir_datos=dir_datos,
    )


def _plan(tmp_path, dir_datos, monkeypatch) -> dict:
    monkeypatch.setattr("agent.agente_base.ClienteGroq", lambda: ClienteFalso())
    return _agente(tmp_path, dir_datos).planificar(
        1, consulta="excursionista desaparecida"
    )["plan"]


def _medios(plan: dict) -> set[str]:
    return {m for fase in plan["fases"] for m in fase["medios"]}


def test_preparar_escenario_copia_y_no_muta_origen(tmp_path):
    origen = RAIZ / "data"
    antes = (origen / "clima.json").read_text(encoding="utf-8")
    destino = preparar_escenario(
        origen,
        tmp_path / "escenario",
        {"viento_kmh": 41, "visibilidad": "mala", "hel_disponible": False},
    )

    clima = json.loads((destino / "clima.json").read_text(encoding="utf-8"))
    assert all(f["viento_kmh"] == 41 for f in clima["franjas"])
    assert all(f["visibilidad_km"] == 3 for f in clima["franjas"])
    equipos = json.loads((destino / "equipos.json").read_text(encoding="utf-8"))
    hel = next(e for e in equipos["equipos"] if e["id"] == "HEL-1")
    assert hel["disponible"] is False
    assert (origen / "clima.json").read_text(encoding="utf-8") == antes


def test_viento_alto_deja_sin_hel_y_dron(tmp_path, monkeypatch):
    destino = preparar_escenario(
        RAIZ / "data", tmp_path / "alto", {"viento_kmh": 41, "visibilidad": "regular"}
    )
    plan = _plan(tmp_path, destino, monkeypatch)
    assert "HEL-1" not in _medios(plan)
    assert "DR-1" not in _medios(plan)


def test_viento_bajo_conserva_hel_y_dron(tmp_path, monkeypatch):
    destino = preparar_escenario(
        RAIZ / "data", tmp_path / "bajo", {"viento_kmh": 20, "visibilidad": "buena"}
    )
    plan = _plan(tmp_path, destino, monkeypatch)
    assert "HEL-1" in _medios(plan)
    assert "DR-1" in _medios(plan)


def test_hel_fuera_de_servicio_se_descarta(tmp_path, monkeypatch):
    destino = preparar_escenario(
        RAIZ / "data",
        tmp_path / "sin-hel",
        {"viento_kmh": 20, "visibilidad": "buena", "hel_disponible": False},
    )
    plan = _plan(tmp_path, destino, monkeypatch)
    assert "HEL-1" not in _medios(plan)
    assert viabilidad_medio("HEL-1", "Z-2", "2026-10-18T06:00/2026-10-18T12:00", destino)["puede"] is False


def test_k9_fuera_de_servicio_se_quita_de_la_noche(tmp_path, monkeypatch):
    destino = preparar_escenario(
        RAIZ / "data",
        tmp_path / "sin-k9",
        {"viento_kmh": 20, "visibilidad": "buena", "k9_disponible": False},
    )
    plan = _plan(tmp_path, destino, monkeypatch)
    assert "K9-1" not in _medios(plan)
    nocturnas = [f for f in plan["fases"] if "23:00" in f["franja"]]
    assert nocturnas and all("EQ-2" in f["medios"] for f in nocturnas)
