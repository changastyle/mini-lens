# -*- coding: utf-8 -*-
"""
GENERATE-ICON.PY
Genera los iconos de MiniLens (negro/amarillo, cluster de hexagonos):
  assets/minilens_icon.svg  (vector)
  assets/minilens_icon.png  (512x512)
  assets/minilens_icon.ico  (multi-size, para el .exe de PyInstaller)

Diseno: 3 hexagonos grandes amarillos + 4 chicos negros con borde amarillo
sobre fondo negro redondeado (misma paleta que la app).

Uso:  python CI-CD-LOCAL/generate-icon.py
"""

import math
import os

# 1 - PALETA DE LA APP (negro/amarillo):
AMARILLO = (245, 197, 24)     # #f5c518
AMARILLO_HEX = "#f5c518"
NEGRO = (26, 26, 26)          # #1a1a1a
NEGRO_HEX = "#1a1a1a"
NEGRO_OSCURO = (13, 13, 13)   # #0d0d0d (relleno de los chicos)

# 2 - CANVAS Y LAYOUT (coordenadas sobre 1024x1024):
CANVAS = 1024
BIG_R = 215
SMALL_R = 88
BIG_HEXES = [(405, 265), (380, 715), (755, 555)]
SMALL_HEXES = [(880, 135), (115, 505), (870, 810), (215, 880)]


def hex_points(cx, cy, r):
    # 1 - CALCULO LOS 6 VERTICES DE UN HEXAGONO PUNTA-ARRIBA:
    pts = []
    for i in range(6):
        a = math.radians(60 * i - 90)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def build_png(out_path):
    # 1 - DIBUJO EN ALTA RESOLUCION Y ACHICO (bordes suaves):
    from PIL import Image, ImageDraw
    S = 2
    size = CANVAS * S
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 2 - FONDO REDONDEADO NEGRO CON BORDE AMARILLO:
    margin = 20 * S
    d.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=190 * S,
        fill=NEGRO + (255,),
        outline=AMARILLO + (255,),
        width=14 * S,
    )

    # 3 - HEXAGONOS GRANDES AMARILLOS:
    for (cx, cy) in BIG_HEXES:
        d.polygon([(x * S, y * S) for (x, y) in hex_points(cx, cy, BIG_R)],
                  fill=AMARILLO + (255,))

    # 4 - HEXAGONOS CHICOS: borde amarillo (hexagono mas grande debajo)
    #     + relleno negro oscuro encima:
    for (cx, cy) in SMALL_HEXES:
        d.polygon([(x * S, y * S) for (x, y) in hex_points(cx, cy, SMALL_R + 14)],
                  fill=AMARILLO + (255,))
        d.polygon([(x * S, y * S) for (x, y) in hex_points(cx, cy, SMALL_R)],
                  fill=NEGRO_OSCURO + (255,))

    # 5 - ACHICO A 512 Y GUARDO:
    img = img.resize((512, 512), Image.LANCZOS)
    img.save(out_path)
    return out_path


def build_ico(png_path, out_path):
    # 1 - CONVIERTO EL PNG A .ICO CON LOS TAMANOS QUE USA WINDOWS:
    from PIL import Image
    img = Image.open(png_path)
    img.save(out_path, format="ICO",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                    (64, 64), (128, 128), (256, 256)])
    return out_path


def _hex_points_attr(cx, cy, r):
    # 1 - LOS 6 VERTICES COMO STRING "x,y x,y ..." PARA EL SVG:
    return " ".join(f"{x:.1f},{y:.1f}" for (x, y) in hex_points(cx, cy, r))


def build_svg(out_path):
    # 1 - MISMO DISENO EN VECTOR (escalable sin perder calidad):
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<svg xmlns="http://www.w3.org/2000/svg" '
                 'viewBox="0 0 1024 1024" width="1024" height="1024">')
    # 1a - FONDO REDONDEADO NEGRO CON BORDE AMARILLO:
    lines.append(f'  <rect x="20" y="20" width="{CANVAS - 40}" '
                 f'height="{CANVAS - 40}" rx="190" fill="{NEGRO_HEX}" '
                 f'stroke="{AMARILLO_HEX}" stroke-width="14"/>')
    # 2 - HEXAGONOS GRANDES AMARILLOS:
    for (cx, cy) in BIG_HEXES:
        pts = " ".join(f"{x:.1f},{y:.1f}" for (x, y) in hex_points(cx, cy, BIG_R))
        lines.append(f'  <polygon points="{pts}" fill="{AMARILLO_HEX}"/>')
    # 3 - HEXAGONOS CHICOS NEGROS CON BORDE AMARILLO:
    for (cx, cy) in SMALL_HEXES:
        lines.append(f'  <polygon points="{_hex_attr(cx, cy, SMALL_R + 14)}" fill="{AMARILLO_HEX}"/>')
        lines.append(f'  <polygon points="{_hex_attr(cx, cy, SMALL_R)}" fill="#0d0d0d"/>')
    lines.append("</svg>")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def _hex_attr(cx, cy, r):
    # 1 - LOS PUNTOS DEL HEXAGONO COMO ATRIBUTO "points" DE SVG:
    return " ".join(f"{x:.1f},{y:.1f}" for (x, y) in hex_points(cx, cy, r))


def main():
    # 1 - RUTA DE ASSETS (assets/ al lado de la carpeta de este script):
    base = os.path.dirname(os.path.abspath(__file__))
    assets = os.path.join(os.path.dirname(base), "assets")
    os.makedirs(assets, exist_ok=True)

    # 2 - GENERO LOS TRES FORMATOS:
    png = build_png(os.path.join(assets, "minilens_icon.png"))
    ico = build_ico(png, os.path.join(assets, "minilens_icon.ico"))
    svg = build_svg(os.path.join(assets, "minilens_icon.svg"))

    # 3 - REPORTE:
    for p in (png, ico, svg):
        print("OK:", p, f"({os.path.getsize(p)} bytes)")


if __name__ == "__main__":
    main()
