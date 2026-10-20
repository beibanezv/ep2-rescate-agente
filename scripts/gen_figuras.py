"""Genera las dos figuras del informe EP2 con PIL (sin dependencias nuevas)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SALIDA = Path(__file__).resolve().parents[1] / "docs" / "figuras"
SALIDA.mkdir(parents=True, exist_ok=True)

AZUL = "#1f3a5f"
TEAL = "#2a9d8f"
ARENA = "#e9c46a"
ROJO = "#c44536"
GRIS = "#f4f6f8"
BORDE = "#c9d1d9"
TEXTO = "#1b1f24"
BLANCO = "#ffffff"

FUENTE = "C:/Windows/Fonts/segoeui.ttf"
FUENTE_B = "C:/Windows/Fonts/segoeuib.ttf"
FUENTE_I = "C:/Windows/Fonts/segoeuii.ttf"


def f(size, bold=False, italic=False):
    ruta = FUENTE_B if bold else (FUENTE_I if italic else FUENTE)
    return ImageFont.truetype(ruta, size)


def caja(d, xy, relleno=BLANCO, borde=BORDE, radio=18, ancho=3):
    d.rounded_rectangle(xy, radius=radio, fill=relleno, outline=borde, width=ancho)


def texto(d, xy, lineas, size=26, color=TEXTO, bold=False, italic=False,
          alineacion="center", espaciado=6):
    fuente = f(size, bold, italic)
    alto = sum(d.textbbox((0, 0), ln, font=fuente)[3] + espaciado for ln in lineas) - espaciado
    y = xy[1] - alto / 2
    for ln in lineas:
        bb = d.textbbox((0, 0), ln, font=fuente)
        ancho = bb[2] - bb[0]
        x = xy[0] - ancho / 2 if alineacion == "center" else xy[0]
        d.text((x, y), ln, font=fuente, fill=color)
        y += (bb[3] - bb[1]) + espaciado


def flecha(d, p1, p2, color=AZUL, ancho=5, cabeza=16):
    d.line([p1, p2], fill=color, width=ancho)
    import math

    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    for lado in (-0.45, 0.45):
        x = p2[0] - cabeza * math.cos(ang + lado)
        y = p2[1] - cabeza * math.sin(ang + lado)
        d.line([p2, (x, y)], fill=color, width=ancho)


def figura_arquitectura():
    W, H = 2200, 1220
    img = Image.new("RGB", (W, H), BLANCO)
    d = ImageDraw.Draw(img)

    texto(d, (1100, 38), ["Arquitectura del agente y orquestación LangGraph"], 40, AZUL, bold=True)

    # Operador
    caja(d, (70, 120, 360, 250), GRIS)
    texto(d, (215, 185), ["Operador", "consulta + --plan"], 25)

    # Agente + nodos
    caja(d, (440, 105, 1590, 300), "#eef4fb", AZUL, ancho=4)
    texto(d, (1015, 135), ["AgenteRastreo  ·  grafo LangGraph"], 27, AZUL, bold=True)
    nodos = ["contexto", "calcular", "publicar", "redactar", "memorizar"]
    x0, ancho, alto, gap = 470, 198, 82, 28
    for i, nombre in enumerate(nodos):
        x = x0 + i * (ancho + gap)
        relleno = ARENA if nombre in ("calcular", "publicar") else BLANCO
        caja(d, (x, 185, x + ancho, 185 + alto), relleno, AZUL, radio=14, ancho=3)
        texto(d, (x + ancho / 2, 185 + alto / 2), [nombre], 25, AZUL, bold=True)
        if i < len(nodos) - 1:
            flecha(d, (x + ancho + 2, 226), (x + ancho + gap - 4, 226), AZUL, 4, 12)

    flecha(d, (362, 186), (436, 186), AZUL, 5)

    # LLM
    caja(d, (1660, 120, 2130, 285), "#fff7e0", "#b08900", ancho=3)
    texto(d, (1895, 170), ["LLM (solo redacta)", "Groq gpt-oss-120b", "o ClienteFalso (--falso)"], 24)
    flecha(d, (1594, 210), (1656, 210), "#b08900", 5)

    # Tools
    caja(d, (70, 385, 1590, 700), GRIS, BORDE, ancho=3)
    texto(d, (830, 415), ["tools/rastreo.py  ·  lectura y escritura validada"], 27, AZUL, bold=True)
    tools = [
        ("leer_caso", "ficha de la persona"),
        ("detalle_zonas", "acceso, altitud, barrido"),
        ("pronostico", "viento y visibilidad"),
        ("equipos_disponibles", "medios y autonomía"),
        ("viabilidad_medio", "regla §3 por medio/zona"),
        ("publicar_plan", "valida y escribe plan-vN"),
    ]
    for i, (nombre, detalle) in enumerate(tools):
        col, fila = i % 3, i // 3
        x = 100 + col * 500
        y = 465 + fila * 105
        caja(d, (x, y, x + 470, y + 86), BLANCO, TEAL, radio=12, ancho=3)
        texto(d, (x + 235, y + 28), [nombre], 24, TEAL, bold=True)
        texto(d, (x + 235, y + 60), [detalle], 20, TEXTO)

    # Guardrail
    caja(d, (1660, 385, 2130, 700), "#fdf0ed", ROJO, ancho=3)
    texto(d, (1895, 430), ["Guardrail de publicar_plan"], 25, ROJO, bold=True)
    texto(d, (1895, 545), ["estructura de fases", "franja ISO", "zona y medio existentes", "no calcula viabilidad"], 22)

    # Almacenes
    almacenes = [
        (70, "Datos del caso", ["data/*.json", "ficha, zonas, clima,", "equipos, planes"]),
        (600, "Conocimiento (RAG)", ["corpus → Chroma", "protocolo y criterios", "citas [F#]"]),
        (1130, "Memoria", ["buffer 20 turnos", "+ recall semántico Chroma", "cita plan v1 en acto 2"]),
        (1660, "Observabilidad", ["logs/trace.jsonl", "LangSmith opcional", "5 pasos por plan"]),
    ]
    for x, titulo, lineas in almacenes:
        caja(d, (x, 790, x + 470, 1110), BLANCO, BORDE, ancho=3)
        d.rectangle((x, 790, x + 470, 860), fill=AZUL)
        texto(d, (x + 235, 825), [titulo], 25, BLANCO, bold=True)
        texto(d, (x + 235, 985), lineas, 23)

    flecha(d, (830, 704), (830, 786), TEAL, 5)
    flecha(d, (1015, 304), (1015, 381), AZUL, 5)

    img.save(SALIDA / "figura-1-arquitectura.png", quality=95)
    return SALIDA / "figura-1-arquitectura.png"


def figura_acto2():
    W, H = 2200, 980
    img = Image.new("RGB", (W, H), BLANCO)
    d = ImageDraw.Draw(img)
    texto(d, (1100, 38), ["Acto 2: el clima invalida la ventana y el plan se adapta"], 40, AZUL, bold=True)

    # Evento
    caja(d, (70, 120, 620, 430), "#fdf0ed", ROJO, ancho=3)
    texto(d, (345, 155), ["Evento de viento", "06:00–12:00"], 27, ROJO, bold=True)
    filas = [("Z-2", "41 km/h"), ("Z-5", "38 km/h"), ("Z-1", "48 km/h")]
    for i, (z, v) in enumerate(filas):
        y = 235 + i * 55
        texto(d, (250, y), [z], 25, TEXTO, bold=True)
        texto(d, (430, y), [v], 25, TEXTO)

    # Decisión
    caja(d, (760, 120, 1430, 430), "#eef4fb", AZUL, ancho=3)
    texto(d, (1095, 155), ["viabilidad_medio()", "aplica protocolo §3"], 26, AZUL, bold=True)
    texto(d, (1095, 255), ["HEL-1: viento ≥ 35 → NO", "DR-1: viento > 40 → NO en Z-2", "DR-1: 38 ≤ 40 → SÍ en Z-5"], 23, TEXTO)
    texto(d, (1095, 385), ["descarte con motivo y cita de regla"], 20, ROJO, italic=True)

    flecha(d, (624, 275), (756, 275), AZUL, 6)

    # Plan v2
    caja(d, (1570, 120, 2130, 430), "#eaf6f3", TEAL, ancho=3)
    texto(d, (1850, 155), ["Plan v2 (publicado)"], 27, TEAL, bold=True)
    plan = [("Z-2", "EQ-1"), ("Z-5", "DR-1"), ("Z-1", "EQ-1")]
    for i, (z, m) in enumerate(plan):
        y = 235 + i * 55
        texto(d, (1700, y), [z], 25, TEXTO, bold=True)
        texto(d, (1950, y), [m], 25, TEAL, bold=True)
    texto(d, (1850, 400), ["fase nocturna sin cambios"], 20, TEXTO, italic=True)

    flecha(d, (1434, 275), (1566, 275), TEAL, 6)

    # Memoria y reevaluación
    caja(d, (70, 530, 1050, 820), "#fff7e0", "#b08900", ancho=3)
    texto(d, (560, 570), ["Memoria de sesión"], 27, "#8a6a00", bold=True)
    texto(d, (560, 650), ["el parte cita el plan v1 previo", "(memoria + memoria-semantica)"], 25)
    texto(d, (560, 755), ["continuidad entre turnos (IE3)"], 21, "#8a6a00", italic=True)

    caja(d, (1130, 530, 2130, 820), "#eef4fb", AZUL, ancho=3)
    texto(d, (1630, 570), ["Reevaluación programada"], 27, AZUL, bold=True)
    texto(d, (1630, 650), ["HEL-1 vuelve si 12:00–18:00 baja de 35 km/h", "Z-2 24 · Z-5 22 · Z-1 26 km/h"], 23)
    texto(d, (1630, 755), ["protocolo §4: replanificar es obligatorio"], 21, AZUL, italic=True)

    flecha(d, (1850, 434), (1850, 526), TEAL, 5)
    flecha(d, (1095, 434), (900, 526), AZUL, 5)

    # Trazabilidad
    caja(d, (70, 870, 2130, 930), GRIS, BORDE, ancho=2)
    texto(d, (1100, 900), ["trace: planificacion → memoria_semantica → plan_publicado → parte_narrativo → memoria"], 22, TEXTO, italic=True)

    img.save(SALIDA / "figura-2-acto2.png", quality=95)
    return SALIDA / "figura-2-acto2.png"


if __name__ == "__main__":
    print(figura_arquitectura())
    print(figura_acto2())
