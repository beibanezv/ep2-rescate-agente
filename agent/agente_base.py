"""Loop base del motor: consulta -> memoria -> recuperar -> responder con citas -> trace.

Cada spike lo usa tal cual o lo extiende:
- `verificaciones_extra(consulta, fragmentos, sesion_id)`: hook para consultar
  herramientas de dominio y devolver [(fuente, texto), ...] que entran al
  prompt como [T#]. Por defecto no hace nada.
- Puerta fuera de dominio: si el mejor fragmento esta a distancia mayor que
  `UMBRAL_FUERA_DE_DOMINIO`, responde `TEXTO_FUERA_DE_DOMINIO` sin llamar al
  LLM. Recalibrar umbral y texto por dominio en cada spike.

(Reemplaza a `AgentePlanificador` de la EP1, sin la capa de dominio turistico.)
"""
import re
from dataclasses import dataclass, field

from agent.llm_client import ClienteGroq, ClienteLLM
from agent.memoria import MemoriaAgente
from agent.observabilidad import traceable
from agent.prompts import SISTEMA_BASE, armar_usuario
from agent.retriever import Fragmento, Recuperador
from agent.trace import Trazador

REGEX_CITAS = re.compile(r"\[\s*(F|T)\s*(\d+)\s*\]")

# Puerta fuera de dominio: distancia del top-1 (menor = mas similar).
# Calibrado 2026-10-15 con el corpus demo del esqueleto: consultas validas
# 0.36-0.71, fuera de dominio 0.86-0.95 -> umbral 0.78. Recalibrar por spike.
UMBRAL_FUERA_DE_DOMINIO = 0.78

TEXTO_FUERA_DE_DOMINIO = (
    "Solo puedo ayudar con los temas de mi base de conocimiento interna. "
    "Reformula tu consulta dentro de ese ambito."
)


@dataclass
class RespuestaBase:
    texto: str
    fragmentos: list[Fragmento] = field(default_factory=list)
    fuentes_citadas: list[str] = field(default_factory=list)
    fuera_de_dominio: bool = False
    archivo_trace: str = ""


class AgenteBase:
    def __init__(
        self,
        llm: ClienteLLM | None = None,
        trazador: Trazador | None = None,
        k: int = 5,
        memoria: MemoriaAgente | None = None,
        recuperador: Recuperador | None = None,
    ):
        self.llm = llm or ClienteGroq()
        self.trazador = trazador or Trazador()
        self.k = k
        self.memoria = memoria or MemoriaAgente()
        # Lazy: Recuperador exige que la coleccion exista (correr ingestion.ingest).
        self.recuperador = recuperador

    def _buscar(self, consulta: str) -> list[Fragmento]:
        if self.recuperador is None:
            self.recuperador = Recuperador()
        return self.recuperador.buscar(consulta, k=self.k)

    def verificaciones_extra(
        self, consulta: str, fragmentos: list[Fragmento], sesion_id: str | None = None
    ) -> list[tuple[str, str]]:
        """Hook de dominio: sobrescribir para agregar resultados [T#] al prompt."""
        return []

    def _extraer_fuentes(
        self, respuesta: str, fragmentos: list[Fragmento], herramientas: list
    ) -> list[str]:
        fuentes: list[str] = []
        for letra, numero in REGEX_CITAS.findall(respuesta):
            n = int(numero)
            if letra == "F" and 1 <= n <= len(fragmentos):
                fuente = fragmentos[n - 1].fuente
            elif letra == "T" and 1 <= n <= len(herramientas):
                fuente = herramientas[n - 1][0]
            else:
                continue
            if fuente not in fuentes:
                fuentes.append(fuente)
        return fuentes

    @traceable("procesar")
    def procesar(self, consulta: str, sesion_id: str | None = None) -> RespuestaBase:
        self.trazador.registrar("consulta", texto=consulta, sesion_id=sesion_id)

        # Memoria IE3/IE4: historial corto + recuerdos semanticos de la sesion.
        bloque_memoria = ""
        recuerdos = []
        if sesion_id:
            bloque_memoria = self.memoria.contexto_para_prompt(sesion_id)
            recuerdos = self.memoria.recuperar(consulta, sesion_id)
            self.trazador.registrar(
                "memoria",
                sesion_id=sesion_id,
                turnos_previos=len(self.memoria.historial(sesion_id, ultimos=20)),
                recuerdos=len(recuerdos),
            )

        fragmentos = self._buscar(consulta)
        self.trazador.registrar(
            "recuperacion",
            fuentes=[f.fuente for f in fragmentos],
            n_fragmentos=len(fragmentos),
        )

        # Puerta fuera de dominio: si nada pertinente a la vista, redirigir sin gastar LLM.
        mejor = fragmentos[0].score if fragmentos else None
        if mejor is None or mejor > UMBRAL_FUERA_DE_DOMINIO:
            self.trazador.registrar("fuera_de_dominio", consulta=consulta, score_top1=mejor)
            if sesion_id:
                self.memoria.registrar_turno(sesion_id, consulta, "fuera de dominio")
            return RespuestaBase(
                texto=TEXTO_FUERA_DE_DOMINIO,
                fuera_de_dominio=True,
                archivo_trace=str(self.trazador.archivo),
            )

        herramientas: list[tuple[str, str]] = [(r.fuente, r.texto) for r in recuerdos]
        herramientas += self.verificaciones_extra(consulta, fragmentos, sesion_id)

        pedido = consulta + ("\n" + bloque_memoria if bloque_memoria else "")
        usuario = armar_usuario(pedido, fragmentos, herramientas or None)
        respuesta = self.llm.completar(SISTEMA_BASE, usuario)
        fuentes = self._extraer_fuentes(respuesta.texto, fragmentos, herramientas)

        self.trazador.registrar(
            "respuesta_final",
            n_fragmentos=len(fragmentos),
            n_herramientas=len(herramientas),
            fuentes_citadas=fuentes,
            modelo=respuesta.modelo,
        )
        if sesion_id:
            self.memoria.registrar_turno(sesion_id, consulta, respuesta.texto[:200])
        return RespuestaBase(
            texto=respuesta.texto,
            fragmentos=fragmentos,
            fuentes_citadas=fuentes,
            archivo_trace=str(self.trazador.archivo),
        )
