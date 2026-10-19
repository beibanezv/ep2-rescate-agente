"""Orquestacion LangGraph del plan de busqueda (IE2).

`contexto -> calcular -> publicar -> redactar -> memorizar`. Los nodos viven en
`AgenteRastreo`; este modulo solo declara el estado compartido y las aristas.
"""
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph


class EstadoPlan(TypedDict, total=False):
    version: int
    motivo_cambio: str
    sesion_id: str | None
    consulta: str
    recuerdo: tuple[str, str] | None
    herramientas: list[tuple[str, str]]
    fragmentos: list[Any]
    fases: list[dict]
    prioridad: list[str]
    motivo: str
    citas: list[str]
    plan: dict
    archivo: str
    parte: str
    fuentes: list[str]
    cito_plan_previo: bool
    archivo_trace: str


def construir_grafo(agente) -> Any:
    """Compila el flujo de planificacion sobre los nodos de `agente`."""
    flujo = StateGraph(EstadoPlan)
    flujo.add_node("contexto", agente._nodo_contexto)
    flujo.add_node("calcular", agente._nodo_calcular)
    flujo.add_node("publicar", agente._nodo_publicar)
    flujo.add_node("redactar", agente._nodo_redactar)
    flujo.add_node("memorizar", agente._nodo_memorizar)
    flujo.set_entry_point("contexto")
    flujo.add_edge("contexto", "calcular")
    flujo.add_edge("calcular", "publicar")
    flujo.add_edge("publicar", "redactar")
    flujo.add_edge("redactar", "memorizar")
    flujo.add_edge("memorizar", END)
    return flujo.compile()
