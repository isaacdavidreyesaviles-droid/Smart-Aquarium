#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puente Serial - Smart Aquarium
===============================

Lee por USB (Serial a 115200 baudios) las líneas que imprime el ESP32
(wemos_sensado_temp_ph.ino) y las sube a Firebase Realtime Database cada
vez que llega una lectura (~cada 2 s), además de guardar un historial cada
30 s.

Formatos de línea que produce el sketch (ver el .ino):

  Lectura válida:
    "Temp: 25.31 C | pH (fijo): 6.5 | sensor pH GPIO34: 1523 mV"

  Lectura inválida (antes de llegar a 3 fallos seguidos):
    "Temp: INVALIDA (motivo) [fallos seguidos: 2] | pH (fijo): 6.5 | sensor pH GPIO34: 1523 mV"

  Lectura inválida justo al llegar al 3er fallo seguido (agrega el aviso
  de que la LCD ya muestra "Error"):
    "Temp: INVALIDA (motivo) [fallos seguidos: 3] -> LCD muestra Error | pH (fijo): 6.5 | sensor pH GPIO34: 1523 mV"

Este script reproduce EXACTAMENTE la misma lógica de estado que usa la
LCD del sketch (función actualizarLCD() del .ino):

  - fallosSeguidos >= 3           -> estado "error"   (la LCD muestra "Error")
  - fallosSeguidos <  3 y ya hubo
    una lectura válida antes      -> estado "ok"       (la LCD conserva el
                                                           último valor bueno)
  - fallosSeguidos <  3 y NUNCA
    hubo una lectura válida       -> estado "sin_datos" (la LCD muestra "---")

Cada lectura se sube con PUT a:
    {databaseURL}/acuario/actual.json?auth={secret}

y cada 30 s se agrega una entrada al historial con POST (push) a:
    {databaseURL}/acuario/historial.json?auth={secret}
recortando el historial a ~200 entradas.

Uso:
    py puente_serial.py

Para salir: Ctrl+C
"""

import json
import os
import re
import sys
import time
import socket

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Falta la librería 'pyserial'. Instala las dependencias con:")
    print("    pip install -r requirements.txt")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Falta la librería 'requests'. Instala las dependencias con:")
    print("    pip install -r requirements.txt")
    sys.exit(1)


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

CARPETA_SCRIPT = os.path.dirname(os.path.abspath(__file__))
RUTA_CONFIG = os.path.join(CARPETA_SCRIPT, "config.json")

BAUDIOS = 115200

# Debe coincidir con FALLOS_PARA_ERROR del archivo .ino (no lo modificamos,
# solo reproducimos su lógica). Si en el futuro cambia el .ino, actualizar
# también este valor.
FALLOS_PARA_ERROR = 3

INTERVALO_HISTORIAL = 30       # segundos entre cada entrada nueva del historial
MAX_ENTRADAS_HISTORIAL = 200   # tope aproximado de entradas guardadas

TIMEOUT_HTTP = 5               # segundos de espera para cada llamada a Firebase
ESPERA_RECONEXION_PUERTO = 3   # segundos entre reintentos de apertura del puerto
ESPERA_BUSQUEDA_PUERTO = 5     # segundos entre reintentos de autodetección

# Identificadores típicos de los adaptadores USB-Serial que trae un ESP32
# (Wemos D1 R32 suele traer un CP210x; los clones chinos suelen traer CH340/CH9102)
PISTAS_ADAPTADOR_USB = ["CP210", "CH340", "CH9102", "SILICON LABS", "WCH", "USB-SERIAL"]


# --------------------------------------------------------------------------
# Expresiones regulares para las líneas del sketch
# --------------------------------------------------------------------------

# "Temp: 25.31 C | pH (fijo): 6.5 | sensor pH GPIO34: 1523 mV"
RE_VALIDA = re.compile(
    r"^Temp:\s*(-?\d+(?:\.\d+)?)\s*C\s*\|\s*pH \(fijo\):\s*([\d.]+)\s*\|\s*"
    r"sensor pH GPIO(\d+):\s*(\d+)\s*mV\s*$"
)

# "Temp: INVALIDA (motivo, puede tener (parentesis)) [fallos seguidos: 2] | pH (fijo): 6.5 | sensor pH GPIO34: 1523 mV"
# El motivo se captura con ".*" (avaro/greedy) porque puede contener sus propios
# paréntesis (ej: "sensor desconectado o sin respuesta (-127)"); el motor de
# regex retrocede hasta encontrar el ") [fallos seguidos:" real, que es único
# en la línea.
RE_INVALIDA = re.compile(
    r"^Temp:\s*INVALIDA\s*\((.*)\)\s*\[fallos seguidos:\s*(\d+)\]"
    r"(?:\s*->\s*LCD muestra Error)?\s*\|\s*pH \(fijo\):\s*([\d.]+)\s*\|\s*"
    r"sensor pH GPIO(\d+):\s*(\d+)\s*mV\s*$"
)


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

def cargar_config():
    if not os.path.isfile(RUTA_CONFIG):
        print("No se encontró config.json en:")
        print(f"    {RUTA_CONFIG}")
        print()
        print("Copia config.example.json como config.json y completa databaseURL")
        print("y secret con los datos de tu proyecto de Firebase. Ejemplo (PowerShell):")
        print('    Copy-Item config.example.json config.json')
        sys.exit(1)

    try:
        with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"No se pudo leer config.json: {e}")
        sys.exit(1)

    faltantes = [c for c in ("databaseURL", "secret") if not config.get(c)]
    if faltantes:
        print("Faltan datos en config.json: " + ", ".join(faltantes))
        print("Revisa LEEME.md para saber dónde obtenerlos en Firebase.")
        sys.exit(1)

    config["databaseURL"] = config["databaseURL"].rstrip("/")
    return config


# --------------------------------------------------------------------------
# Detección del puerto serie
# --------------------------------------------------------------------------

def detectar_puerto_esp32():
    """Devuelve el primer puerto COM que parezca un adaptador USB-Serial de un
    ESP32 (CP210x / CH340 / CH9102), o None si no encuentra ninguno."""
    puertos = list(serial.tools.list_ports.comports())
    for p in puertos:
        texto = f"{p.description or ''} {p.manufacturer or ''} {p.hwid or ''}".upper()
        if any(pista in texto for pista in PISTAS_ADAPTADOR_USB):
            return p.device
    # Si hay un único puerto disponible, lo usamos como último recurso.
    if len(puertos) == 1:
        return puertos[0].device
    return None


def esperar_puerto(puerto_configurado):
    """Bloquea hasta encontrar un puerto para usar (configurado o autodetectado)."""
    if puerto_configurado:
        return puerto_configurado

    avisado = False
    while True:
        puerto = detectar_puerto_esp32()
        if puerto:
            return puerto
        if not avisado:
            print("Buscando un ESP32 conectado por USB (CP210x/CH340)... "
                  "conéctalo o indica el puerto en config.json.")
            avisado = True
        time.sleep(ESPERA_BUSQUEDA_PUERTO)


# --------------------------------------------------------------------------
# Parseo de líneas -> estado tipo LCD
# --------------------------------------------------------------------------

class EstadoLectura:
    """Reproduce hayTempBuena / ultimaTemp del sketch, del lado de la PC."""

    def __init__(self):
        self.hay_temp_buena = False
        self.ultima_temp = None

    def procesar_linea(self, linea):
        """Devuelve un dict listo para subir a Firebase, o None si la línea
        no es una línea de lectura (ej. mensajes de arranque)."""

        m = RE_VALIDA.match(linea)
        if m:
            temp = float(m.group(1))
            ph = float(m.group(2))
            ph_mv = int(m.group(4))
            self.ultima_temp = temp
            self.hay_temp_buena = True
            return {
                "temp": round(temp, 2),
                "estado": "ok",
                "ph": ph,
                "phMv": ph_mv,
                "fallos": 0,
                "ts": ts_actual_ms(),
            }

        m = RE_INVALIDA.match(linea)
        if m:
            fallos = int(m.group(2))
            ph = float(m.group(3))
            ph_mv = int(m.group(5))

            if fallos >= FALLOS_PARA_ERROR:
                estado = "error"
            elif self.hay_temp_buena:
                estado = "ok"  # conserva el último valor válido, igual que la LCD
            else:
                estado = "sin_datos"  # la LCD muestra "---"

            return {
                "temp": (round(self.ultima_temp, 2) if self.hay_temp_buena else None),
                "estado": estado,
                "ph": ph,
                "phMv": ph_mv,
                "fallos": fallos,
                "ts": ts_actual_ms(),
            }

        return None  # línea que no es de lectura (banners, avisos de arranque, etc.)


def ts_actual_ms():
    return int(time.time() * 1000)


# --------------------------------------------------------------------------
# Firebase Realtime Database (REST)
# --------------------------------------------------------------------------

def url_actual(config):
    return f"{config['databaseURL']}/acuario/actual.json?auth={config['secret']}"


def url_historial(config):
    return f"{config['databaseURL']}/acuario/historial.json?auth={config['secret']}"


def subir_actual(config, payload):
    try:
        r = requests.put(url_actual(config), data=json.dumps(payload), timeout=TIMEOUT_HTTP,
                          headers={"Content-Type": "application/json"})
        if r.status_code >= 400:
            print(f"  Firebase respondió {r.status_code} al subir la lectura actual: {r.text[:200]}")
            return False
        return True
    except (requests.exceptions.RequestException, socket.timeout) as e:
        print(f"  Sin conexión a internet / Firebase (actual.json): {e}")
        return False


def agregar_historial(config, payload):
    try:
        r = requests.post(url_historial(config), data=json.dumps(payload), timeout=TIMEOUT_HTTP,
                           headers={"Content-Type": "application/json"})
        if r.status_code >= 400:
            print(f"  Firebase respondió {r.status_code} al agregar al historial: {r.text[:200]}")
            return
        recortar_historial(config)
    except (requests.exceptions.RequestException, socket.timeout) as e:
        print(f"  Sin conexión a internet / Firebase (historial.json): {e}")


def recortar_historial(config):
    """Mantiene el historial en ~MAX_ENTRADAS_HISTORIAL entradas, borrando las
    más viejas. Las claves que genera Firebase con push() son ordenables
    cronológicamente como texto."""
    url = f"{config['databaseURL']}/acuario/historial.json?shallow=true&auth={config['secret']}"
    try:
        r = requests.get(url, timeout=TIMEOUT_HTTP)
        if r.status_code >= 400:
            return
        claves = r.json()
        if not claves:
            return
        claves = sorted(claves.keys())
        exceso = len(claves) - MAX_ENTRADAS_HISTORIAL
        if exceso <= 0:
            return
        for clave in claves[:exceso]:
            url_borrar = f"{config['databaseURL']}/acuario/historial/{clave}.json?auth={config['secret']}"
            try:
                requests.delete(url_borrar, timeout=TIMEOUT_HTTP)
            except (requests.exceptions.RequestException, socket.timeout):
                pass  # si falla el recorte no pasa nada grave, se reintenta en 30s
        print(f"  Historial recortado: se borraron {exceso} entrada(s) antigua(s).")
    except (requests.exceptions.RequestException, socket.timeout, ValueError) as e:
        print(f"  No se pudo recortar el historial (se reintentará más tarde): {e}")


# --------------------------------------------------------------------------
# Bucle principal
# --------------------------------------------------------------------------

def hora():
    return time.strftime("%H:%M:%S")


def texto_estado(estado):
    return {"ok": "OK", "error": "ERROR", "sin_datos": "SIN DATOS"}.get(estado, estado)


def ejecutar_puente(config):
    puerto_configurado = (config.get("puerto") or "").strip() or None
    ultimo_push_historial = 0.0

    print("=== Puente Serial - Smart Aquarium ===")
    print(f"Firebase: {config['databaseURL']}")
    if puerto_configurado:
        print(f"Puerto fijado en config.json: {puerto_configurado}")
    else:
        print("Puerto: autodetección (CP210x/CH340/CH9102)")
    print("Presiona Ctrl+C para salir.")
    print()

    while True:  # bucle de (re)conexión al puerto USB
        puerto = esperar_puerto(puerto_configurado)
        try:
            ser = serial.Serial(puerto, BAUDIOS, timeout=2)
            # Pequeña pausa: al abrir el puerto muchas placas ESP32 se resetean.
            time.sleep(0.5)
            ser.reset_input_buffer()
        except (serial.SerialException, OSError) as e:
            print(f"[{hora()}] No se pudo abrir el puerto {puerto}: {e}")
            print(f"  Reintentando en {ESPERA_RECONEXION_PUERTO}s... "
                  "(¿está el Monitor Serial del IDE abierto? ciérralo)")
            time.sleep(ESPERA_RECONEXION_PUERTO)
            continue

        print(f"[{hora()}] Conectado al puerto {puerto} a {BAUDIOS} baudios.")
        estado_lectura = EstadoLectura()

        try:
            while True:
                try:
                    crudo = ser.readline()
                except (serial.SerialException, OSError) as e:
                    print(f"[{hora()}] Se perdió la conexión USB: {e}")
                    break

                if not crudo:
                    continue  # timeout de lectura, normal, seguimos esperando

                linea = crudo.decode("utf-8", errors="ignore").strip()
                if not linea:
                    continue

                payload = estado_lectura.procesar_linea(linea)
                if payload is None:
                    # Línea informativa del sketch (arranque, DS18B20 encontrados, etc.)
                    print(f"[{hora()}] (info ESP32) {linea}")
                    continue

                ok_envio = subir_actual(config, payload)
                marca = "Firebase OK" if ok_envio else "Firebase FALLÓ (sigo intentando)"
                print(
                    f"[{hora()}] Temp={payload['temp']} estado={texto_estado(payload['estado'])} "
                    f"pH={payload['ph']} mV={payload['phMv']} fallos={payload['fallos']} -> {marca}"
                )

                ahora = time.time()
                if ahora - ultimo_push_historial >= INTERVALO_HISTORIAL:
                    agregar_historial(config, payload)
                    ultimo_push_historial = ahora

        finally:
            try:
                ser.close()
            except Exception:
                pass

        print(f"[{hora()}] Puerto cerrado. Reintentando conexión en {ESPERA_RECONEXION_PUERTO}s...")
        time.sleep(ESPERA_RECONEXION_PUERTO)


def main():
    config = cargar_config()
    try:
        ejecutar_puente(config)
    except KeyboardInterrupt:
        print()
        print("Saliendo del puente serial (Ctrl+C). ¡Hasta luego!")
        sys.exit(0)


if __name__ == "__main__":
    main()
