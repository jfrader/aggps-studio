# AgGPS Studio

[English](README.md) | Español | [Português (Brasil)](README.pt-BR.md)

Suba un **AgGPS.zip** de Trimble y descargue:

1. `<Establecimiento>_AgGPS.zip` listo para copiar al **Case IH AFS Pro 700**
2. `<Establecimiento>_Shapefile.zip` como alternativa lista para copiar
3. Un **PDF** imprimible con mapas de taipas para el chofer
4. `<Establecimiento>_Mapas_lotes.zip` con un JPG independiente por lote
5. `<Establecimiento>_paquete_completo.zip` con todos los archivos y las instrucciones

Este proceso se cargó correctamente en un Puma 210 con AFS Pro 700. Genera shapefiles 2D seguros para el tractor y mantiene separados los dos formatos de importación.

## Ejecutar con Docker

```bash
cp .env.example .env
# Defina una contraseña larga en AGGPS_STUDIO_PASSWORD.
docker compose up --build --detach
```

Abra `http://localhost:8765`. En producción use HTTPS y `COOKIE_SECURE=true`.

## Ejecutar por línea de comandos

Se requiere Python 3.13.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python process.py /ruta/AgGPS.zip --out ./salida --no-sat --language es
```

Los documentos para el operador admiten `es`, `en` y `pt-BR`. Español es el idioma predeterminado. Cada ZIP y PDF entregado usa el nombre seguro del establecimiento como prefijo; por ejemplo, `DEMO_FARM_AgGPS.zip`.

## Aplicación de escritorio (Windows x64 / Linux x64)

Descargue `aggps-studio-0.4.0-*.zip` (artefactos de CI o release). Extraiga la carpeta onedir.

Ejecute el lanzador GUI normal:

- Windows: `AgGPS Studio.exe`
- Linux: `chmod +x "AgGPS Studio" && ./"AgGPS Studio"`

El lanzador usa `--windowed` (sin consola). `--version` y `--smoke-test` funcionan para verificación y salen antes de cualquier GUI.

Linux requiere librerías de sistema WebKitGTK/GTK (el bundle son sólo archivos de aplicación portables; no es completamente estático):

```bash
sudo apt-get update
sudo apt-get install -y gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 gir1.2-gtk-3.0
```

Windows: Edge WebView2 Evergreen suele estar presente en sistemas Windows modernos. Si la GUI falla con error de webview, instale desde la página oficial de Microsoft WebView2 (https://developer.microsoft.com/en-us/microsoft-edge/webview2/). El runtime no viene incluido en este paquete.

Construir desde fuente (reproducible):

```bash
python -m pip install -r requirements-build-desktop.txt
python build_desktop.py
# los zips quedan en dist/; la construcción usa temp de plataforma para intermedios
```

Vea `BUNDLE_README.txt` dentro de cada bundle y `AGENTS.md`.

## Paquetes USB

Las dos descargas USB no contienen carpetas extra ni archivos de instrucciones:

```text
DEMO_FARM_AgGPS.zip
  AgGPS/Data/<Grower>/<Farm>/<Field>/...

DEMO_FARM_Shapefile.zip
  Shapefile/<Slug>_Bdy.shp
  Shapefile/<Slug>_Taipa.shp
```

Descomprima un ZIP y copie su única carpeta a la raíz del USB:

| Alternativa | La raíz debe contener | Source en Import2 |
|---|---|---|
| `<Establecimiento>_AgGPS.zip` | `E:\AgGPS\Data\...` | Non Pro 700 1 |
| `<Establecimiento>_Shapefile.zip` | `E:\Shapefile\Plot12_Bdy.shp` | Shapefile |

La vía recomendada usa el USB propio del tractor: apague, retírelo, deje la carpeta `.cn1` intacta y copie `AgGPS` o `Shapefile` a la raíz, al lado de `.cn1`. Nunca formatee ese USB, copie archivos dentro de `.cn1`, copie el ZIP cerrado ni coloque ambos formatos juntos. Devuelva el mismo USB, encienda, espere el mensaje de copia interna y abra Import2.

Si no quiere conectar el USB del tractor a una computadora, use un segundo pendrive FAT32 de 8–32 GB con solo `AgGPS` o solo `Shapefile`. Deje que el Pro 700 lo copie, apague y vuelva a colocar el USB `.cn1` antes de abrir Import2. Sin `.cn1`, pueden no aparecer Grower/Farm/Field.

Importe `*_Bdy` como **Boundary** y después `*_Taipa` como **Guidance / Line / Multiswath**. Auto-select funciona solo cuando el tractor está físicamente dentro del polígono Boundary. Un reinicio adicional después de importar puede ser normal.

`<Establecimiento>_Mapas_lotes.zip` contiene archivos planos como `Plot12.jpg`, uno por lote con Boundary y taipas sobre la imagen satelital. `<Establecimiento>_paquete_completo.zip` contiene ambos ZIP del tractor, el PDF, el ZIP de imágenes, `LEAME.txt` e `INDICE_CAMPOS.txt`.

## Pruebas

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python process.py --help
```

Las pruebas crean shapefiles 2D sintéticos. No agregue exportaciones de clientes ni archivos de campo generados al repositorio.
