"""CLI del esqueleto: consulta -> respuesta citada con trazabilidad.

Uso:
    python main.py "que regla aplica al registrar una decision" --falso --pasos
    python main.py "que especialidad tiene la cuadrilla A" --falso --sesion demo1
    python main.py "consulta" --falso --salida      # demuestra la tool de escritura
    python main.py "reporte del caso" --plan --falso --sesion caso-morado
        # planificacion de rescate: publica data/planes/plan-v<N>.json

Con --falso usa ClienteFalso (determinista, sin cuota Groq); por defecto usa
ClienteLangChain (ChatGroq via LangChain, openai/gpt-oss-120b) con tracing
LangSmith si hay LANGSMITH_API_KEY en .env.
"""
import argparse
import json
import sys
from pathlib import Path

from agent.agente_base import AgenteBase
from agent.llm_client import ClienteFalso, ClienteGroq, ClienteLangChain
from agent.observabilidad import init_langsmith
from agent.rastreo import AgenteRastreo

RAIZ = Path(__file__).resolve().parent


def mostrar_trace(archivo: str, omitir: int = 0) -> None:
    if not archivo:
        return
    lineas = Path(archivo).read_text(encoding="utf-8").strip().split("\n")
    print("\n--- TRAZABILIDAD (trace.jsonl) ---")
    for linea in lineas[omitir:]:
        e = json.loads(linea)
        partes = [f"[{e['paso']:02d}] {e['tipo']}"]
        for clave, valor in e.items():
            if clave in ("paso", "tipo", "hora_utc"):
                continue
            partes.append(f"{clave}={valor}")
        print(" | ".join(partes))


def _siguiente_version(dir_planes: Path) -> int:
    existentes = [int(p.stem.split("-v")[1]) for p in dir_planes.glob("plan-v*.json")]
    return max(existentes, default=0) + 1


def mostrar_plan(r: dict) -> None:
    plan = r["plan"]
    print(f"--- PLAN v{plan['version']} ({r['archivo']}) ---")
    print("Prioridad de zonas: " + " > ".join(plan["prioridad_zonas"]))
    for f in plan["fases"]:
        print(f"{f['franja']} | {f['zona']}: {', '.join(f['medios'])} | {f['objetivo']}")
    print("Motivo del cambio: " + (plan["motivo_cambio"] or "(version inicial)"))
    print("Citas: " + " | ".join(plan["citas"]))
    if r["cito_plan_previo"]:
        print("Memoria: el parte cita el plan previo de la sesion.")
    print("\n--- PARTE ---")
    print(r["parte"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Esqueleto EP2: motor de agente con RAG, memoria y trazabilidad.",
        epilog='Ejemplo: python main.py "que regla aplica al registrar una decision" --falso --pasos',
    )
    parser.add_argument("consulta", help="consulta (entre comillas)")
    parser.add_argument("--falso", action="store_true", help="usar ClienteFalso determinista (sin cuota Groq)")
    parser.add_argument("--groq-directo", action="store_true", help="usar ClienteGroq (SDK crudo) en vez de ClienteLangChain")
    parser.add_argument("--sesion", default=None, help="id de sesion para memoria corto/largo plazo (ej: demo1)")
    parser.add_argument("--pasos", action="store_true", help="mostrar cada paso del loop (trace.jsonl)")
    parser.add_argument("--salida", action="store_true", help="registrar la respuesta con la tool de escritura de ejemplo")
    parser.add_argument("--plan", action="store_true", help="planificacion de rescate: publica data/planes/plan-v<N>.json")
    args = parser.parse_args()

    # Consola Windows (cp1252) rompia con respuestas LLM con unicode: UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    init_langsmith()
    if args.falso:
        llm = ClienteFalso()
    elif args.groq_directo:
        llm = ClienteGroq()
    else:
        llm = ClienteLangChain()
    agente = AgenteRastreo(llm=llm) if args.plan else AgenteBase(llm=llm)

    archivo_trace = RAIZ / "logs" / "trace.jsonl"
    lineas_previas = len(archivo_trace.read_text(encoding="utf-8").strip().split("\n")) if archivo_trace.exists() else 0

    print(f"Consulta: {args.consulta}")
    print(f"LLM: {type(llm).__name__}\n")

    if args.plan:
        plan = agente.planificar(
            _siguiente_version(RAIZ / "data" / "planes"),
            sesion_id=args.sesion,
            consulta=args.consulta,
        )
        mostrar_plan(plan)
        fuentes = ", ".join(plan["fuentes_citadas"]) if plan["fuentes_citadas"] else "(ninguna)"
        print(f"\nFuentes citadas:   {fuentes}")
        print(f"Trace:             {plan['archivo_trace']}")
        if args.pasos:
            mostrar_trace(plan["archivo_trace"], omitir=lineas_previas)
        return 0

    r = agente.procesar(args.consulta, sesion_id=args.sesion)

    if args.salida:
        if r.fuera_de_dominio:
            print("Fuera de dominio: no se registra salida.")
        else:
            from tools.ejemplo import describir_salida, registrar_salida

            out = registrar_salida(
                "respuesta",
                "respuesta-agente",
                {"consulta": args.consulta, "texto": r.texto, "fuentes": r.fuentes_citadas},
            )
            print(describir_salida(out))

    print("--- RESPUESTA ---")
    print(r.texto)
    print()
    print(f"Fuera de dominio:  {'si' if r.fuera_de_dominio else 'no'}")
    print(f"Fuentes citadas:   {', '.join(r.fuentes_citadas) if r.fuentes_citadas else '(ninguna)'}")
    print(f"Trace:             {r.archivo_trace}")

    if args.pasos:
        mostrar_trace(r.archivo_trace, omitir=lineas_previas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
