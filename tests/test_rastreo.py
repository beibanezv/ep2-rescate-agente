"""Tests dorados del spike de rescate (brief §7): plan v1, evento de viento, noche segura.

Sin red: ClienteFalso + RecuperadorFalso + Chroma de memoria desactivado.
Los datos se copian a tmp_path para editar el clima sin tocar `data/`.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from agent.llm_client import ClienteFalso
from agent.memoria import MemoriaAgente
from agent.rastreo import AgenteRastreo
from agent.retriever import Fragmento
from agent.trace import Trazador
from tools.rastreo import pronostico, publicar_plan, viabilidad_medio

RAIZ = Path(__file__).resolve().parents[1]

# Evento del Acto 2 (brief §6): franjas 06:00-12:00 -> (viento km/h, visibilidad km).
EVENTO_VIENTO = {"Z-1": (48, 3), "Z-2": (41, 6), "Z-3": (52, 4), "Z-4": (55, 4), "Z-5": (38, 7)}


class RecuperadorFalso:
    def buscar(self, consulta, k=5, filtro=None):
        return [
            Fragmento(id="c1", texto="Fase I nocturna: no se ingresa a zonas tecnicas.",
                      tipo="documento", fuente="protocolo-busqueda", score=0.2),
            Fragmento(id="c2", texto="prioridad = probabilidad x facilidad / tiempo de barrido.",
                      tipo="documento", fuente="criterios-prioridad", score=0.3),
        ]


def _datos(tmp_path) -> Path:
    destino = tmp_path / "data"
    shutil.copytree(RAIZ / "data", destino, ignore=shutil.ignore_patterns("planes"))
    return destino


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


def _evento_viento(dir_datos: Path) -> None:
    ruta = dir_datos / "clima.json"
    clima = json.loads(ruta.read_text(encoding="utf-8"))
    for franja in clima["franjas"]:
        if franja["desde"].endswith("06:00") and franja["hasta"].endswith("12:00"):
            viento, vis = EVENTO_VIENTO[franja["zona"]]
            franja["viento_kmh"], franja["visibilidad_km"] = viento, vis
    ruta.write_text(json.dumps(clima, ensure_ascii=False, indent=2), encoding="utf-8")


def _inicio(fase) -> datetime:
    return datetime.fromisoformat(fase["franja"].split("/")[0])


def _fases_manana(plan) -> list:
    return [f for f in plan["fases"] if _inicio(f).hour == 6]


def _es_nocturna(fase) -> bool:
    hora = _inicio(fase).hour
    return hora >= 18 or hora < 6


def test_plan_v1_prioriza_ruta_y_usa_helicoptero(tmp_path, monkeypatch):
    agente = _agente(tmp_path, _datos(tmp_path), monkeypatch)
    r = agente.planificar(
        1, sesion_id="caso-morado", consulta="excursionista desaparecida; ultimo contacto en el mirador"
    )
    plan = r["plan"]
    assert plan["version"] == 1
    prio = plan["prioridad_zonas"]
    assert prio[0] == "Z-2"
    assert prio.index("Z-2") < prio.index("Z-3") and prio.index("Z-2") < prio.index("Z-4")

    manana = _fases_manana(plan)
    assert any("HEL-1" in f["medios"] for f in manana)
    assert any("DR-1" in f["medios"] for f in manana)
    nocturnas = [f for f in plan["fases"] if _es_nocturna(f)]
    assert nocturnas and all(f["zona"] not in {"Z-3", "Z-4"} for f in nocturnas)
    assert Path(r["archivo"]).exists()


def test_evento_viento_replanifica(tmp_path, monkeypatch):
    datos = _datos(tmp_path)
    _evento_viento(datos)
    agente = _agente(tmp_path, datos, monkeypatch)
    r = agente.planificar(2, sesion_id="caso-morado", consulta="replanifica el operativo por el viento")
    plan = r["plan"]
    manana = _fases_manana(plan)
    assert manana and all("HEL-1" not in f["medios"] for f in manana)
    assert plan["motivo_cambio"]

    vientos = {v["zona"]: v["viento_kmh"] for v in pronostico(dir_datos=datos) if v["desde"].endswith("06:00")}
    for fase in manana:
        if "DR-1" in fase["medios"]:
            assert vientos[fase["zona"]] < 40
    assert any("DR-1" in f["medios"] for f in manana)  # Z-5 sigue dentro del maximo del dron


def test_fase_nocturna_segura(tmp_path, monkeypatch):
    datos = _datos(tmp_path)
    agente = _agente(tmp_path, datos, monkeypatch)
    plan1 = agente.planificar(1)["plan"]
    _evento_viento(datos)
    plan2 = agente.planificar(2, sesion_id="caso-morado")["plan"]
    for plan in (plan1, plan2):
        for fase in plan["fases"]:
            if _es_nocturna(fase) and fase["zona"] in {"Z-3", "Z-4"}:
                pytest.fail(f"plan v{plan['version']} asigna zona tecnica de noche: {fase}")
    v = viabilidad_medio("EQ-2", "Z-3", "2026-10-17T22:00/2026-10-18T06:00", dir_datos=datos)
    assert not v["puede"]


def test_publicar_plan_valida_estructura(tmp_path):
    datos = _datos(tmp_path)
    base = {
        "franja": "2026-10-17T23:00/2026-10-18T05:00",
        "zona": "Z-2",
        "medios": ["EQ-2"],
        "objetivo": "prueba",
    }
    with pytest.raises(ValueError):
        publicar_plan(1, [dict(base, franja="no-es-franja")], ["Z-2"], "", [], dir_datos=datos)
    with pytest.raises(ValueError):
        publicar_plan(1, [dict(base, zona="Z-9")], ["Z-2"], "", [], dir_datos=datos)
    with pytest.raises(ValueError):
        publicar_plan(1, [dict(base, medios=["EQ-9"])], ["Z-2"], "", [], dir_datos=datos)
    with pytest.raises(ValueError):
        publicar_plan(1, [base], ["Z-9"], "", [], dir_datos=datos)
    r = publicar_plan(1, [base], ["Z-2"], "", [], dir_datos=datos)
    assert Path(r["archivo"]).exists()
