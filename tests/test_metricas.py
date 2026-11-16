"""Tests del arnés de observabilidad cuantitativa."""
import pytest

from agent.metricas import fases_desde_trace, leer_metricas, medir, resumen


def test_medir_persiste_latencia_y_memoria(tmp_path):
    archivo = tmp_path / "metricas.jsonl"
    with medir("operacion", archivo=archivo) as medicion:
        medicion["detalle"] = "ok"
    assert medicion["operacion"] == "operacion"
    assert medicion["latencia_ms"] >= 0
    assert medicion["memoria_pico_kb"] >= 0
    assert medicion["error"] is None
    assert leer_metricas(archivo) == [medicion]


def test_medir_registra_y_relanza_errores(tmp_path):
    archivo = tmp_path / "metricas.jsonl"
    with pytest.raises(ValueError):
        with medir("fallo", archivo=archivo):
            raise ValueError("boom")
    guardado = leer_metricas(archivo)[0]
    assert guardado["error"] == "ValueError: boom"


def test_fases_desde_trace_calcula_deltas():
    eventos = [
        {"tipo": "consulta", "t_ms": 1000},
        {"tipo": "recuperacion", "t_ms": 1125},
        {"tipo": "respuesta_final", "t_ms": 1400},
    ]
    fases = fases_desde_trace(eventos)
    assert [f["de"] for f in fases] == ["consulta", "recuperacion"]
    assert [f["latencia_ms"] for f in fases] == [125, 275]


def test_resumen_agrega_latencia_y_tasa_error():
    mediciones = [
        {"latencia_ms": 10, "error": None, "memoria_pico_kb": 100},
        {"latencia_ms": 30, "error": "x", "memoria_pico_kb": 200},
    ]
    res = resumen(mediciones)
    assert res["n"] == 2
    assert res["latencia_p50_ms"] == 20
    assert res["latencia_p95_ms"] == 30
    assert res["tasa_error"] == 0.5
    assert res["memoria_pico_kb"] == 200
    assert resumen([]) == {}
