#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador de QR - Smart Aquarium
==================================

Genera "qr_acuario.png": un código QR que apunta a la página pública
(url_pagina en config.json), con un texto debajo, listo para imprimir y
pegar junto a la pecera.

Uso:
    py generar_qr.py
"""

import json
import os
import sys

try:
    import qrcode
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Faltan librerías. Instala las dependencias con:")
    print("    pip install -r requirements.txt")
    sys.exit(1)


CARPETA_SCRIPT = os.path.dirname(os.path.abspath(__file__))
RUTA_CONFIG = os.path.join(CARPETA_SCRIPT, "config.json")
RUTA_SALIDA = os.path.join(CARPETA_SCRIPT, "qr_acuario.png")

TEXTO_PIE = "Smart Aquarium — escanea para ver en vivo"


def cargar_url_pagina():
    if not os.path.isfile(RUTA_CONFIG):
        print("No se encontró config.json en:")
        print(f"    {RUTA_CONFIG}")
        print("Copia config.example.json como config.json y completa 'url_pagina'")
        print("con el enlace de tu página en GitHub Pages.")
        sys.exit(1)

    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        config = json.load(f)

    url = (config.get("url_pagina") or "").strip()
    if not url or url.startswith("https://TU-"):
        print("El campo 'url_pagina' de config.json todavía no está configurado.")
        print("Edítalo con la URL real de tu página de GitHub Pages y vuelve a correr este script.")
        sys.exit(1)

    return url


def generar_qr(url, texto_pie, ruta_salida):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img_qr = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # Lienzo final: el QR arriba + una franja blanca abajo con el texto.
    margen = 24
    alto_texto = 60
    ancho = img_qr.width + margen * 2
    alto = img_qr.height + margen * 2 + alto_texto

    lienzo = Image.new("RGB", (ancho, alto), "white")
    lienzo.paste(img_qr, (margen, margen))

    dibujo = ImageDraw.Draw(lienzo)
    fuente = _cargar_fuente(18)

    caja_texto = dibujo.textbbox((0, 0), texto_pie, font=fuente)
    ancho_texto = caja_texto[2] - caja_texto[0]
    x_texto = max((ancho - ancho_texto) // 2, 0)
    y_texto = img_qr.height + margen + (alto_texto - (caja_texto[3] - caja_texto[1])) // 2

    dibujo.text((x_texto, y_texto), texto_pie, fill="black", font=fuente)

    lienzo.save(ruta_salida)
    return ruta_salida


def _cargar_fuente(tamano):
    # Intenta usar una fuente típica de Windows; si no está disponible, usa la
    # fuente por defecto de Pillow (más fea, pero nunca falla).
    candidatas = ["arialbd.ttf", "arial.ttf", "segoeui.ttf", "DejaVuSans-Bold.ttf"]
    for nombre in candidatas:
        try:
            return ImageFont.truetype(nombre, tamano)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def main():
    url = cargar_url_pagina()
    ruta = generar_qr(url, TEXTO_PIE, RUTA_SALIDA)
    print("QR generado correctamente:")
    print(f"    {ruta}")
    print(f"Apunta a: {url}")


if __name__ == "__main__":
    main()
