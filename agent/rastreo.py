"""Agente de dominio: coordinador de operaciones de busqueda y rescate andino.

La decision de asignacion (prioridad de zonas, fases y medios) se calcula en
codigo determinista (viabilidad en `tools/rastreo.py`); el LLM solo redacta el
parte narrativo. Extiende `AgenteBase`:

- `verificaciones_extra`: inyecta clima y equipos como [T#].
- `planificar(version, motivo_cambio=None)`: prioriza -> fases -> publica el
  plan -> memoria de sesion -> parte. En v>1 cita el plan previo de la sesion.
"""
import json
from pathlib import Path

from agent.agente_base import AgenteBase
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
    def __init__(self, *args, dir_datos: str | Path | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.dir_datos = Path(dir_datos) if dir_datos else None

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
        # Fase I: anclaje nocturno en las 2 zonas probables mas faciles (senderos/caminos).
        for zid in probables[:2]:
            fases.append({
                "franja": FRANJA_NOCTURNA,
                "zona": zid,
                "medios": ["EQ-2", "K9-1"],
                "objetivo": f"Anclaje nocturno en {zonas[zid]['nombre']} (senderos y caminos)",
            })

        descartes: list[str] = []
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

    @traceable("planificar")
    def planificar(
        self,
        version: int,
        motivo_cambio: str | None = None,
        sesion_id: str | None = None,
        consulta: str = "",
    ) -> dict:
        """Calcula, valida y publica el plan; devuelve tambien el parte del LLM."""
        self.trazador.registrar("planificacion", version=version, sesion_id=sesion_id)
        fases, prioridad, motivo_auto, citas = self._construir_plan(version)
        publicado = publicar_plan(
            version, fases, prioridad, motivo_cambio or motivo_auto, citas,
            dir_datos=self.dir_datos,
        )
        plan = {k: publicado[k] for k in ("version", "fases", "prioridad_zonas", "motivo_cambio", "citas")}
        self.trazador.registrar(
            "plan_publicado",
            archivo=publicado["archivo"],
            n_fases=len(fases),
            prioridad=">".join(prioridad),
            motivo=plan["motivo_cambio"] or "(version inicial)",
        )

        recuerdo_previo = self._recuerdo_plan_previo(sesion_id, version)
        herramientas = ([recuerdo_previo] if recuerdo_previo else []) + self.verificaciones_extra(
            consulta, [], sesion_id
        )
        fragmentos = self._buscar(consulta or "plan de busqueda por fases de una persona desaparecida")
        pedido = (
            (consulta or "plan de busqueda")
            + "\nPLAN YA PUBLICADO (decisiones calculadas y validadas en codigo):\n"
            + json.dumps(plan, ensure_ascii=False)
        )
        usuario = armar_usuario(pedido, fragmentos, herramientas or None)
        respuesta = self.llm.completar(SISTEMA_BASE, usuario)
        fuentes = self._extraer_fuentes(respuesta.texto, fragmentos, herramientas)
        self.trazador.registrar(
            "parte_narrativo",
            modelo=respuesta.modelo,
            cita_plan_previo=bool(recuerdo_previo),
            fuentes_citadas=fuentes,
        )
        if sesion_id:
            self.memoria.registrar_turno(
                sesion_id,
                consulta,
                resumen=respuesta.texto[:200],
                extra={
                    "plan_version": version,
                    "plan_archivo": publicado["archivo"],
                    "plan_resumen": _resumen_plan(plan),
                },
            )
            self.trazador.registrar("memoria", sesion_id=sesion_id, plan_version=version)
        return {
            "plan": plan,
            "archivo": publicado["archivo"],
            "parte": respuesta.texto,
            "fuentes_citadas": fuentes,
            "cito_plan_previo": bool(recuerdo_previo),
            "archivo_trace": str(self.trazador.archivo),
        }
