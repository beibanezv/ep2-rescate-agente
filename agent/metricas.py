"""Observabilidad cuantitativa: latencia, errores y memoria pico del agente.

Complementa ``trace.py`` (qué pasó) con cuánto tardó, cuánto falló y cuánto
memoria consumió cada corrida. Sin dependencias nuevas: usa solo stdlib.
"""
from __future__ import annotations

import functools
import json
import math
import statistics
import time
import tracemalloc
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

RAIZ = Path(__file__).resolve().parents[1]
ARCHIVO_METRICAS = RAIZ / "logs" / "metricas.jsonl"


def _persistir(medicion: dict, archivo: Path | None) -> None:
    destino = archivo or ARCHIVO_METRICAS
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("a", encoding="utf-8") as f:
        f.write(json.dumps(medicion, ensure_ascii=False) + "\n")


@contextmanager
def medir(operacion: str, archivo: Path | None = None) -> Iterator[dict]:
    """Mide una operación y deja el resultado en el dict que entrega al ``with``."""
    iniciado = time.perf_counter()
    empezo_trazado = not tracemalloc.is_tracing()
    if empezo_trazado:
        tracemalloc.start()
    medicion = {"operacion": operacion, "latencia_ms": 0.0, "error": None, "memoria_pico_kb": 0.0}
    try:
        yield medicion
    except Exception as exc:
        medicion["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        medicion["latencia_ms"] = round((time.perf_counter() - iniciado) * 1000, 2)
        _, pico = tracemalloc.get_traced_memory()
        medicion["memoria_pico_kb"] = round(pico / 1024, 1)
        if empezo_trazado:
            tracemalloc.stop()
        _persistir(medicion, archivo)


def medir_llamada(operacion: str):
    """Decorador: mide cada llamada y la persiste en logs/metricas.jsonl."""

    def decorador(func):
        @functools.wraps(func)
        def envolvente(*args, **kwargs):
            with medir(operacion):
                return func(*args, **kwargs)

        return envolvente

    return decorador


def fases_desde_trace(eventos: list[dict]) -> list[dict]:
    """Latencia entre eventos consecutivos, usando la marca ``t_ms`` del trace."""
    fases: list[dict] = []
    anterior: tuple[str, int] | None = None
    for evento in eventos:
        actual = evento.get("t_ms")
        if actual is None:
            continue
        if anterior is not None:
            fases.append({
                "de": anterior[0],
                "a": evento["tipo"],
                "latencia_ms": round(actual - anterior[1], 2),
            })
        anterior = (evento["tipo"], actual)
    return fases


def _percentil(valores: list[float], fraccion: float) -> float:
    """Percentil por rango más cercano (nearest-rank)."""
    ordenados = sorted(valores)
    indice = min(len(ordenados) - 1, math.ceil(fraccion * len(ordenados)) - 1)
    return ordenados[indice]


def resumen(mediciones: list[dict]) -> dict:
    """Agrega latencia (media/p50/p95/máx), tasa de error y pico de memoria."""
    if not mediciones:
        return {}
    latencias = [m["latencia_ms"] for m in mediciones]
    return {
        "n": len(mediciones),
        "latencia_media_ms": round(statistics.mean(latencias), 2),
        "latencia_p50_ms": round(statistics.median(latencias), 2),
        "latencia_p95_ms": round(_percentil(latencias, 0.95), 2),
        "latencia_max_ms": max(latencias),
        "tasa_error": round(sum(bool(m.get("error")) for m in mediciones) / len(mediciones), 3),
        "memoria_pico_kb": max(m.get("memoria_pico_kb", 0) for m in mediciones),
    }


def leer_metricas(archivo: Path | None = None) -> list[dict]:
    """Lee el JSONL de métricas; devuelve [] si aún no existe."""
    origen = archivo or ARCHIVO_METRICAS
    if not origen.exists():
        return []
    with origen.open(encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]
