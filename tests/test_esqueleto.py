"""Smoke tests del esqueleto: sin red, sin cuota, sin Chroma real."""
import pytest

from agent.agente_base import AgenteBase
from agent.llm_client import ClienteFalso
from agent.memoria import MemoriaAgente
from agent.retriever import Fragmento
from agent.trace import Trazador
from ingestion.ingest import chunk_texto
from tools.ejemplo import registrar_salida


class RecuperadorFalso:
    def __init__(self, fragmentos):
        self._f = fragmentos

    def buscar(self, consulta, k=5, filtro=None):
        return self._f[:k]


def _agente(tmp_path, fragmentos, con_memoria=True):
    return AgenteBase(
        llm=ClienteFalso(),
        trazador=Trazador(archivo=tmp_path / "trace.jsonl"),
        memoria=MemoriaAgente(
            dir_chroma=tmp_path / "chroma",
            archivo_sesiones=tmp_path / "sesiones.json",
        ) if con_memoria else None,
        recuperador=RecuperadorFalso(fragmentos),
    )


def test_chunk_texto_respeta_max_y_solapa():
    chunks = chunk_texto("palabra " * 200, max_chars=100, overlap=10)
    assert all(len(c) <= 100 for c in chunks)
    assert len(chunks) > 1


def test_cliente_falso_cita_marcadores_deduplicados_y_ordenados():
    r = ClienteFalso().completar("sistema", "contexto [F1] y [T2] y de nuevo [F1]")
    assert "[F1] [T2]" in r.texto


def test_memoria_buffer_separa_sesiones(tmp_path, monkeypatch):
    mem = MemoriaAgente(
        dir_chroma=tmp_path / "chroma",
        archivo_sesiones=tmp_path / "sesiones.json",
    )
    monkeypatch.setattr(mem, "_coleccion", lambda: None)
    mem.registrar_turno("s1", "consulta uno", resumen="se decidio A", extra={"ticket": "T-1"})
    mem.registrar_turno("s2", "consulta dos")
    assert mem.historial("s1")[0]["consulta"] == "consulta uno"
    assert mem.historial("s2")[0]["consulta"] == "consulta dos"
    prompt = mem.contexto_para_prompt("s1")
    assert "consulta uno" in prompt and "T-1" in prompt
    assert mem.recuperar("algo", "s1") == []


def test_agente_responde_y_cita_fuentes(tmp_path, monkeypatch):
    fragmentos = [
        Fragmento(id="1", texto="La regla dice X.", tipo="documento", fuente="manual-operativo", score=0.1),
    ]
    agente = _agente(tmp_path, fragmentos)
    monkeypatch.setattr(agente.memoria, "_coleccion", lambda: None)
    r = agente.procesar("que dice la regla", sesion_id="t1")
    assert not r.fuera_de_dominio
    assert r.fuentes_citadas == ["manual-operativo"]
    assert len(agente.memoria.historial("t1")) == 1


def test_puerta_fuera_de_dominio_no_gasta_llm(tmp_path):
    fragmentos = [Fragmento(id="1", texto="x", tipo="documento", fuente="f", score=0.9)]
    agente = _agente(tmp_path, fragmentos, con_memoria=False)
    r = agente.procesar("receta de pan integral")
    assert r.fuera_de_dominio
    assert "base de conocimiento" in r.texto
    assert r.fuentes_citadas == []


def test_tool_escritura_valida_y_persiste(tmp_path):
    with pytest.raises(ValueError):
        registrar_salida("Nombre Invalido!", "prueba", {"a": 1}, dir_salidas=tmp_path)
    with pytest.raises(ValueError):
        registrar_salida("ok", "prueba", {}, dir_salidas=tmp_path)
    r = registrar_salida("ok", "prueba", {"a": 1}, dir_salidas=tmp_path)
    assert (tmp_path / "ok.json").exists()
    assert r["tipo"] == "prueba"

def test_cliente_langchain_reserva_tokens_y_baja_razonamiento(monkeypatch):
    import langchain_groq
    from agent.llm_client import ClienteLangChain

    capturado = {}

    class ChatFalso:
        def __init__(self, **kwargs):
            capturado.update(kwargs)

        def invoke(self, mensajes):
            return type("Respuesta", (), {"content": "parte narrativo"})()

    monkeypatch.setattr(langchain_groq, "ChatGroq", ChatFalso)
    r = ClienteLangChain().completar("sistema", "usuario")
    assert r.texto == "parte narrativo"
    assert capturado["reasoning_effort"] == "low"
    assert capturado["max_tokens"] >= 2048


def test_extrae_citas_aunque_el_modelo_deje_espacios():
    from agent.agente_base import AgenteBase
    from agent.retriever import Fragmento

    fragmentos = [Fragmento(id="f1", texto="protocolo", fuente="protocolo-busqueda", tipo="protocolo")]
    fuentes = AgenteBase._extraer_fuentes(
        None, "aplica la regla [ F1 ] y el dato [ T1 ].", fragmentos, [("clima", "viento")]
    )
    assert fuentes == ["protocolo-busqueda", "clima"]
