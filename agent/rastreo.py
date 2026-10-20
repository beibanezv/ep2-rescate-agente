"""Agente de dominio: coordinador de operaciones de busqueda y rescate andino.

La decision de asignacion (prioridad de zonas, fases y medios) se calcula en
codigo determinista (viabilidad en `tools/rastreo.py`); el LLM solo redacta el
parte narrativo. Extiende `AgenteBase`:

- `verificaciones_extra`: inyecta clima y equipos como [T#].
- `planificar(version, motivo_cambio=None)`: prioriza -> fases -> publica el
  plan -> memoria de sesion -> parte. En v>1 cita el plan previo de la sesion.
"""
import json
import re
import unicodedata
from pathlib import Path

from agent.agente_base import AgenteBase
from agent.grafo import EstadoPlan, construir_grafo
from agent.observabilidad import traceable
from agent.prompts import SISTEMA_BASE, armar_usuario
from tools.rastreo import (
    ALTITUD_TECNICA_M,
    detalle_zonas,
    equipos_disponibles,
    leer_caso,
    pronostico,
    publicar_plan,
    viabilidad_medio,
)

# El caso simulado ocurre en la noche del 17 al 18 de octubre de 2026.
FRANJA_NOCTURNA = "2026-10-17T23:00/2026-10-18T05:00"
FRANJA_MANANA = "2026-10-18T06:00/2026-10-18T12:00"
FRANJA_TARDE = "2026-10-18T12:00/2026-10-18T18:00"

CITAS_BASE = [
    "protocolo-busqueda 2: fase I nocturna no ingresa a zonas tecnicas ni altas y cierra antes del amanecer",
    "protocolo-busqueda 3: helicoptero viento < 35 km/h y visibilidad > 5 km, solo de dia",
    "protocolo-busqueda 3: dron viento maximo 40 km/h, solo con luz diurna",
    "protocolo-busqueda 3: brigadas y K9 no ingresan a zonas altas (Z-3/Z-4) sin aclimatacion",
    "criterios-prioridad: ultimo contacto primero; ruta declarada y variantes despues; tecnicas al final",
]
CITA_REPLANIFICADO = (
    "protocolo-busqueda 4: si un medio pierde su ventana (clima, luz, autonomia), "
    "el replanificado es obligatorio antes de continuar"
)

TEXTO_FUERA_DE_DOMINIO_RESCATE = (
    "Solo puedo ayudar con el operativo de busqueda y rescate del caso El Morado "
    "(zonas, equipos, clima, protocolo y plan). No puedo responder consultas fuera "
    "de ese alcance. Prueba con: '¿Que equipos hay disponibles?', "
    "'¿Que zonas son tecnicas?', '¿Por que se descarto HEL-1?'."
)

# El corpus es pequeno y los scores no separan solos: una consulta valida puede
# quedar en 0.85 y una ajena en 0.72. Por eso manda la clave de dominio.
CLAVES_RESCATE = (
    "rescate", "busqueda", "operativo", "plan", "fase", "zona", "equipo", "medio",
    "clima", "pronostico", "viento", "visibilidad", "helo", "helicoptero", "dron",
    "protocolo", "prioridad", "tecnica", "altitud", "sendero", "ruta", "perro",
    "guia", "persona", "desaparecida", "excursionista", "morado", "ficha",
    "ultimo contacto", "noche", "nocturno", "barrido", "replanifica", "asignar",
    "buscar", "m torres", "dr 1", "hel 1", "eq 1", "k9", "que paso", "llover",
    "lluvia", "nieve", "vivo", "viva", "herido", "herida", "salud",
)


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower()).strip()


def _tiene_claves_rescate(consulta: str) -> bool:
    texto = _normalizar(consulta)
    return any(
        re.search(rf"\b{re.escape(clave)}(?:es|s)?\b", texto)
        for clave in CLAVES_RESCATE
    )


def _probabilidad(zona: dict, ficha: dict) -> float:
    """Probabilidad del corpus: ultimo contacto > ruta declarada > punto de retorno."""
    if zona["id"] in ficha.get("ultimo_contacto", ""):
        return 1.0
    if zona["id"] in ficha.get("ruta_declarada", ""):
        return 0.75
    if zona.get("refugios"):
        return 0.5
    return 0.25


def _facilidad(zona: dict) -> float:
    """Facilidad de barrido del corpus: dron adecuado y acceso vehicular suman."""
    facilidad = 1.0
    if zona.get("dron") == "adecuado":
        facilidad += 0.2
    if "vehicular" in zona.get("acceso", ""):
        facilidad += 0.2
    return facilidad


def _resumen_plan(plan: dict) -> str:
    partes = [f"prioridad {'>'.join(plan['prioridad_zonas'])}"]
    partes += [f"{f['franja']} {f['zona']} [{','.join(f['medios'])}]" for f in plan["fases"]]
    return "; ".join(partes)[:400]


class AgenteRastreo(AgenteBase):
    texto_fuera_de_dominio = TEXTO_FUERA_DE_DOMINIO_RESCATE

    def __init__(self, *args, dir_datos: str | Path | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.dir_datos = Path(dir_datos) if dir_datos else None
        self.grafo = construir_grafo(self)

    def verificaciones_extra(
        self, consulta: str, fragmentos: list, sesion_id: str | None = None
    ) -> list[tuple[str, str]]:
        """Hook IE2: clima vigente y medios disponibles entran al prompt como [T#]."""
        clima = " | ".join(
            f"{f['zona']} {f['desde']} -> {f['hasta']}: viento {f['viento_kmh']} km/h, "
            f"vis {f['visibilidad_km']} km"
            for f in pronostico(dir_datos=self.dir_datos)
        )
        equipos = " | ".join(
            f"{e['id']} {e['nombre']} ({e['tipo']}, desde {e['disponible_desde']}): "
            f"{e['restricciones']}"
            for e in equipos_disponibles(self.dir_datos)
        )
        return [("clima-simulado", clima), ("equipos-disponibles", equipos)]

    def _fuera_de_dominio(self, consulta: str, fragmentos: list) -> bool:
        if not consulta.strip():
            return False
        if _tiene_claves_rescate(consulta):
            return False
        mejor = fragmentos[0].score if fragmentos else None
        return mejor is None or mejor > 0.70

    def _plan_publicado(self) -> tuple[str, str] | None:
        base = Path(self.dir_datos) if self.dir_datos else Path(__file__).resolve().parents[1] / "data"
        archivos = list((base / "planes").glob("plan-v*.json"))
        if not archivos:
            return None
        archivo = max(archivos, key=lambda p: int(p.stem.split("-v")[1]))
        plan = json.loads(archivo.read_text(encoding="utf-8"))
        return ("plan-publicado", "PLAN YA PUBLICADO: " + json.dumps(plan, ensure_ascii=False))

    def consultar(self, consulta: str, sesion_id: str | None = None):
        """Responde una consulta libre con RAG, tools y el plan publicado si existe."""
        extra = []
        plan = self._plan_publicado()
        if plan:
            extra.append(plan)
        return self.procesar(consulta, sesion_id=sesion_id, herramientas_extra=extra)

    def _prioridad_zonas(self) -> list[str]:
        """Aplica `prioridad = probabilidad x facilidad / tiempo de barrido` (corpus)."""
        ficha = leer_caso(self.dir_datos)
        zonas = detalle_zonas(self.dir_datos)

        def score(z: dict) -> float:
            return _probabilidad(z, ficha) * _facilidad(z) / z["barrido_terrestre_h"]

        return [z["id"] for z in sorted(zonas, key=lambda z: (-score(z), z["id"]))]

    def _construir_plan(self, version: int) -> tuple[list[dict], list[str], str, list[str]]:
        zonas = {z["id"]: z for z in detalle_zonas(self.dir_datos)}
        ficha = leer_caso(self.dir_datos)
        prioridad = self._prioridad_zonas()
        tecnicas = {zid for zid, z in zonas.items() if z["altitud_m"] >= ALTITUD_TECNICA_M}
        probables = [zid for zid in prioridad if zid not in tecnicas]

        fases: list[dict] = []
        descartes: list[str] = []
        # Fase I: anclaje nocturno en las 2 zonas probables mas faciles (senderos/caminos).
        for zid in probables[:2]:
            medios_noche = []
            base = next(f for f in pronostico(zid, self.dir_datos) if f["desde"].endswith("22:00"))
            franja = {**base, "desde": FRANJA_NOCTURNA.split("/")[0], "hasta": FRANJA_NOCTURNA.split("/")[1]}
            for medio in ("EQ-2", "K9-1"):
                v = viabilidad_medio(medio, zid, franja, self.dir_datos)
                if v["puede"]:
                    medios_noche.append(medio)
                else:
                    descartes.append(
                        f"{medio} no opera en {zid} de 22:00 a 06:00: "
                        f"{'; '.join(v['motivos'])} ({v['regla']})"
                    )
            if medios_noche:
                fases.append({
                    "franja": FRANJA_NOCTURNA,
                    "zona": zid,
                    "medios": medios_noche,
                    "objetivo": f"Anclaje nocturno en {zonas[zid]['nombre']} (senderos y caminos)",
                })

        ruta = ficha.get("ruta_declarada", "")
        for i, zid in enumerate(probables):
            medios: list[str] = []
            if i < 2:  # vuelo diurno sobre las 2 zonas mas probables de la ruta
                for medio in ("HEL-1", "DR-1"):
                    v = viabilidad_medio(medio, zid, FRANJA_MANANA, self.dir_datos)
                    if v["puede"]:
                        medios.append(medio)
                    else:
                        descartes.append(
                            f"{medio} no opera en {zid} de 06:00 a 12:00: "
                            f"{'; '.join(v['motivos'])} ({v['regla']})"
                        )
            if zid not in ruta or not medios:
                # EQ-1 cubre las variantes fuera de la ruta; si no hay medio aereo, refuerza.
                medios.append("EQ-1")
            fases.append({
                "franja": FRANJA_MANANA,
                "zona": zid,
                "medios": medios,
                "objetivo": f"Barrido diurno de {zonas[zid]['nombre']} y variantes",
            })

        motivo = ""
        citas = list(CITAS_BASE)
        if version > 1:
            motivo = "Replanificacion por cambio de pronostico: " + "; ".join(descartes)
            citas.append(CITA_REPLANIFICADO)
            tarde = [
                zid
                for zid in probables
                if viabilidad_medio("HEL-1", zid, FRANJA_TARDE, self.dir_datos)["puede"]
            ]
            if tarde:
                vientos = ", ".join(
                    f"{zid} {f['viento_kmh']} km/h"
                    for zid in tarde
                    for f in pronostico(zid, self.dir_datos)
                    if f["desde"].endswith("12:00")
                )
                motivo += f". Se propone reevaluar HEL-1 en 12:00-18:00: {vientos} (bajo 35 km/h)"
        return fases, prioridad, motivo, citas

    def _recuerdo_plan_previo(self, sesion_id: str | None, version: int):
        if not sesion_id:
            return None
        for turno in reversed(self.memoria.historial(sesion_id, ultimos=20)):
            if turno.get("plan_version") and turno["plan_version"] < version:
                return (
                    f"memoria:{sesion_id}",
                    f"Plan v{turno['plan_version']} previo de la sesion "
                    f"(archivo: {turno.get('plan_archivo', '?')}): {turno.get('plan_resumen', '')}",
                )
        return None

    # Nodos del grafo (agent/grafo.py): cada uno lee y amplia el estado comun.
    def _nodo_contexto(self, estado: EstadoPlan) -> dict:
        version = estado["version"]
        sesion_id = estado.get("sesion_id")
        consulta = estado.get("consulta", "")
        self.trazador.registrar("planificacion", version=version, sesion_id=sesion_id)
        recuerdo = self._recuerdo_plan_previo(sesion_id, version)
        semanticos = []
        if sesion_id:
            semanticos = self.memoria.recuperar(consulta, sesion_id)
            self.trazador.registrar(
                "memoria_semantica", sesion_id=sesion_id, recuerdos=len(semanticos)
            )
        herramientas = [
            (f"memoria-semantica:{sesion_id}", r.texto) for r in semanticos
        ]
        herramientas += ([recuerdo] if recuerdo else []) + self.verificaciones_extra(
            consulta, [], sesion_id
        )
        fragmentos = estado.get("fragmentos")
        if fragmentos is None:
            fragmentos = self._buscar(
                consulta or "plan de busqueda por fases de una persona desaparecida"
            )
        return {"recuerdo": recuerdo, "herramientas": herramientas, "fragmentos": fragmentos}

    def _nodo_calcular(self, estado: EstadoPlan) -> dict:
        fases, prioridad, motivo, citas = self._construir_plan(estado["version"])
        return {"fases": fases, "prioridad": prioridad, "motivo": motivo, "citas": citas}

    def _nodo_publicar(self, estado: EstadoPlan) -> dict:
        publicado = publicar_plan(
            estado["version"],
            estado["fases"],
            estado["prioridad"],
            estado.get("motivo_cambio") or estado["motivo"],
            estado["citas"],
            dir_datos=self.dir_datos,
        )
        plan = {
            k: publicado[k]
            for k in ("version", "fases", "prioridad_zonas", "motivo_cambio", "citas")
        }
        self.trazador.registrar(
            "plan_publicado",
            archivo=publicado["archivo"],
            n_fases=len(estado["fases"]),
            prioridad=">".join(estado["prioridad"]),
            motivo=plan["motivo_cambio"] or "(version inicial)",
        )
        return {"plan": plan, "archivo": publicado["archivo"]}

    def _nodo_redactar(self, estado: EstadoPlan) -> dict:
        pedido = (
            (estado.get("consulta") or "plan de busqueda")
            + "\nPLAN YA PUBLICADO (decisiones calculadas y validadas en codigo):\n"
            + json.dumps(estado["plan"], ensure_ascii=False)
        )
        usuario = armar_usuario(pedido, estado["fragmentos"], estado["herramientas"] or None)
        respuesta = self.llm.completar(SISTEMA_BASE, usuario)
        fuentes = self._extraer_fuentes(respuesta.texto, estado["fragmentos"], estado["herramientas"])
        self.trazador.registrar(
            "parte_narrativo",
            modelo=respuesta.modelo,
            cita_plan_previo=bool(estado.get("recuerdo")),
            fuentes_citadas=fuentes,
        )
        return {"parte": respuesta.texto, "fuentes": fuentes}

    def _nodo_memorizar(self, estado: EstadoPlan) -> dict:
        sesion_id = estado.get("sesion_id")
        if sesion_id:
            self.memoria.registrar_turno(
                sesion_id,
                estado.get("consulta", ""),
                resumen=estado["parte"][:200],
                extra={
                    "plan_version": estado["version"],
                    "plan_archivo": estado["archivo"],
                    "plan_resumen": _resumen_plan(estado["plan"]),
                },
            )
            self.trazador.registrar(
                "memoria", sesion_id=sesion_id, plan_version=estado["version"]
            )
        return {
            "cito_plan_previo": bool(estado.get("recuerdo")),
            "archivo_trace": str(self.trazador.archivo),
        }

    @traceable("planificar")
    def planificar(
        self,
        version: int,
        motivo_cambio: str | None = None,
        sesion_id: str | None = None,
        consulta: str = "",
    ) -> dict:
        """Ejecuta el grafo: calcula, publica el plan y devuelve el parte del LLM."""
        fragmentos = None
        if consulta.strip():
            fragmentos = self._buscar(consulta)
            if self._fuera_de_dominio(consulta, fragmentos):
                mejor = fragmentos[0].score if fragmentos else None
                self.trazador.registrar(
                    "fuera_de_dominio", consulta=consulta, score_top1=mejor
                )
                if sesion_id:
                    self.memoria.registrar_turno(
                        sesion_id,
                        consulta,
                        resumen=self.texto_fuera_de_dominio[:200],
                    )
                return {
                    "fuera_de_dominio": True,
                    "texto": self.texto_fuera_de_dominio,
                    "parte": self.texto_fuera_de_dominio,
                    "plan": None,
                    "fuentes_citadas": [],
                    "archivo": "",
                    "cito_plan_previo": False,
                    "archivo_trace": str(self.trazador.archivo),
                }
        estado = self.grafo.invoke({
            "version": version,
            "motivo_cambio": motivo_cambio or "",
            "sesion_id": sesion_id,
            "consulta": consulta,
            "fragmentos": fragmentos,
        })
        return {
            "fuera_de_dominio": False,
            "plan": estado["plan"],
            "archivo": estado["archivo"],
            "parte": estado["parte"],
            "fuentes_citadas": estado["fuentes"],
            "cito_plan_previo": estado["cito_plan_previo"],
            "archivo_trace": estado["archivo_trace"],
        }
