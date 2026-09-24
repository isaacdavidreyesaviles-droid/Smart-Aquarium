# Smart Aquarium — Panel web en vivo

Este paquete conecta el ESP32 (por USB, sin WiFi) con una página web pública
en GitHub Pages, usando Firebase Realtime Database como intermediario:

```
ESP32 --USB (115200)--> puente_serial.py (esta PC) --REST--> Firebase --> docs/index.html (GitHub Pages, cualquier celular)
```

La PC con Windows debe quedar **encendida y con `puente_serial.py` corriendo**
todo el tiempo que se quiera mostrar datos en vivo (no hay servidor en la
nube leyendo el USB: el puente es esta PC).

## Archivos

- `puente_serial.py` — lee el puerto serie del ESP32 y sube los datos a Firebase.
- `config.example.json` — plantilla de configuración (copiar a `config.json`).
- `database.rules.json` — reglas de seguridad de Realtime Database.
- `generar_qr.py` — genera `qr_acuario.png` con la URL de la página pública.
- `docs/index.html` — la página pública (esto es lo que se publica en GitHub Pages).
- `requirements.txt` — dependencias de Python.

## Pasos

### 1. Crear el proyecto de Firebase

1. Ir a <https://console.firebase.google.com/> y crear un proyecto nuevo
   (puede ser gratis, plan Spark).
2. En el menú lateral, entrar a **Compilación > Realtime Database** y
   pulsar **Crear base de datos**. Elegir una ubicación y empezar en modo
   "bloqueado" (ya vamos a pegar nuestras propias reglas).

### 2. Obtener la `databaseURL` y el secreto de la base de datos

1. La **databaseURL** aparece arriba de la tabla de datos, algo como
   `https://tu-proyecto-default-rtdb.REGION.firebasedatabase.app`.
   Cópiala tal cual (sin la barra `/` final).
2. Para el **secreto**: ir a ⚙️ **Configuración del proyecto** (el engranaje,
   junto a "Descripción general del proyecto") **> Cuentas de servicio >
   Secretos de la base de datos**. Ahí se puede revelar o generar un
   secreto. Cópialo.
   - Este secreto da acceso total de lectura/escritura a la base de datos.
     Trátalo como una contraseña: no lo subas a GitHub (por eso
     `config.json` está en `.gitignore`) y no lo pongas en `docs/index.html`
     (la página pública NO necesita el secreto, solo lee).

### 3. Pegar las reglas de seguridad

1. En Realtime Database, pestaña **Reglas**.
2. Reemplazar el contenido por el de `database.rules.json` (de esta carpeta)
   y pulsar **Publicar**.
3. Esto deja `/acuario` en lectura pública (para que la página web y
   cualquier celular puedan verlo) y en escritura solo para quien tenga el
   secreto (nuestro puente).

### 4. Crear el repositorio en GitHub y activar Pages

1. Crear un repositorio nuevo en GitHub (puede ser público) y subir el
   contenido de esta carpeta `acuario_web` (sin `config.json`, que ya está
   ignorado).
2. En el repositorio: **Settings > Pages**.
3. En "Build and deployment" > "Source" elegir **Deploy from a branch**,
   rama `main` (o la que uses) y carpeta **`/docs`**. Guardar.
4. Después de uno o dos minutos, GitHub muestra la URL pública, algo como
   `https://tu-usuario.github.io/tu-repositorio/`.

### 5. Editar la URL de Firebase dentro de `docs/index.html`

1. Abrir `docs/index.html` con un editor de texto.
2. Buscar la línea (cerca del inicio del `<script>`):
   ```js
   const DATABASE_URL = "https://TU-PROYECTO-default-rtdb.REGION.firebasedatabase.app";
   ```
3. Reemplazarla por la `databaseURL` real obtenida en el paso 2 (sin `/`
   al final). Guardar y volver a subir el archivo a GitHub (Pages se
   actualiza solo).

### 6. Instalar las dependencias de Python

En la carpeta `acuario_web`, con PowerShell:

```powershell
pip install -r requirements.txt
```

### 7. Configurar y correr el puente serial

1. Copiar `config.example.json` como `config.json`:
   ```powershell
   Copy-Item config.example.json config.json
   ```
2. Editar `config.json` y completar:
   - `databaseURL`: la misma URL del paso 2.
   - `secret`: el secreto del paso 2.
   - `puerto`: dejar en `""` para autodetección (recomendado), o poner el
     puerto exacto (ej. `"COM5"`) si la autodetección falla.
   - `url_pagina`: la URL de GitHub Pages del paso 4 (la usa `generar_qr.py`).
3. **Importante:** cerrar el **Monitor Serial del Arduino IDE** (o
   cualquier otro programa que tenga abierto el puerto COM del ESP32):
   solo un programa a la vez puede usar el puerto USB.
4. Correr el puente:
   ```powershell
   py puente_serial.py
   ```
   Debería mostrar `Conectado al puerto COMx...` y luego una línea por
   cada lectura que sube a Firebase. Para salir: `Ctrl+C`.
5. Dejar esta ventana corriendo y la PC encendida mientras se quiera que la
   página muestre datos en vivo. Si se desconecta el USB o falla internet,
   el script reintenta solo (no hace falta reiniciarlo), y se ve el aviso
   en la consola.

### 8. Generar el código QR

```powershell
py generar_qr.py
```

Esto crea `qr_acuario.png` en esta misma carpeta, con el texto
"Smart Aquarium — escanea para ver en vivo" debajo, listo para imprimir y
pegar junto a la pecera.

## Resumen de para qué sirve cada dato

- **Temperatura**: la real, leída del DS18B20 por el ESP32.
- **pH**: siempre 6.5 (valor fijo, el sensor está conectado pero sin
  calibrar) — así lo indica también la LCD física y el sketch.
- **mV del sensor de pH**: solo evidencia de que el sensor está conectado,
  no se usa para calcular el pH mostrado.
- **Estado** (`ok` / `error` / `sin_datos`): reproduce exactamente la
  lógica de la LCD del ESP32 (fallos seguidos de lectura de temperatura).

## Problemas comunes

- **"No se encontró config.json"**: falta copiar `config.example.json` a
  `config.json` y completarlo (paso 7).
- **El puerto no se detecta**: cerrar el Monitor Serial del IDE, revisar el
  cable USB (algunos son solo de carga), o poner el puerto manualmente en
  `config.json` (verlo en el Administrador de dispositivos de Windows,
  "Puertos (COM y LPT)").
- **La página dice "Sin conexión con el acuario"**: revisar que
  `puente_serial.py` siga corriendo en la PC y que la PC tenga internet.
- **La página no carga datos nunca**: revisar que la `DATABASE_URL` dentro
  de `docs/index.html` sea la correcta y que las reglas de la base de datos
  (paso 3) estén publicadas.
