# AgGPS Studio

English | [Español](README.es.md) | [Português (Brasil)](README.pt-BR.md)

Upload a Trimble **AgGPS.zip** and download:

1. A ready-to-copy `<Farm>_AgGPS.zip` for the **Case IH AFS Pro 700**
2. A ready-to-copy `<Farm>_Shapefile.zip` alternative
3. A printable **PDF** of taipa maps for the driver
4. `<Farm>_Mapas_lotes.zip` with one standalone JPG map per field
5. `<Farm>_paquete_completo.zip` with every deliverable and the instructions

This pipeline has loaded successfully on a Puma 210 with an AFS Pro 700. It emits 2D tractor-safe shapefiles and keeps the two supported import layouts separate.

Agent instructions: [`AGENTS.md`](AGENTS.md). Domain contract: [`SPEC.md`](SPEC.md). Hosting: [`DEPLOY.md`](DEPLOY.md).

## Run with Docker

```bash
cp .env.example .env
# Set a long AGGPS_STUDIO_PASSWORD in .env.
docker compose up --build --detach
```

Open `http://localhost:8765`. Production deployments must use HTTPS and set `COOKIE_SECURE=true`.

## Run the CLI

Python 3.13 is required.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python process.py /path/to/AgGPS.zip --out ./salida --no-sat --language en
```

Generated operator material supports `es`, `en`, and `pt-BR`. Spanish is the default. Every delivered ZIP and PDF uses the safe farm name as its prefix; for example, `DEMO_FARM_AgGPS.zip`.

## Desktop app (Windows x64 / Linux x64)

Download `aggps-studio-0.4.3-*.zip` (CI artifacts or release). Extract the onedir folder.

Run the normal GUI launcher:

- Windows: `AgGPS Studio.exe`
- Linux: `chmod +x "AgGPS Studio" && ./"AgGPS Studio"`

The launcher is `--windowed` (no console). `--version` and `--smoke-test` work for verification and exit before any GUI.

Linux requires system WebKitGTK/GTK libraries (bundle is portable application files only; do not claim fully static):

Ubuntu 24.04+ / Debian testing+:

```bash
sudo apt-get update
sudo apt-get install -y gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 gir1.2-gtk-3.0
```

Arch Linux:

```bash
sudo pacman -S --needed webkit2gtk-4.1 gtk3
```

The launcher follows the desktop's native GTK backend and supports Wayland and X11.

Windows: Edge WebView2 Evergreen is usually present on modern systems. If the GUI reports a webview error, download the Evergreen installer from the official Microsoft WebView2 page (https://developer.microsoft.com/en-us/microsoft-edge/webview2/). The runtime is not bundled inside this package.

Build from source (reproducible):

```bash
python -m pip install -r requirements-build-desktop.txt
python build_desktop.py
# zips land in dist/; build uses platform temp for intermediates
```

See `BUNDLE_README.txt` inside each bundle and `AGENTS.md`.

## USB Downloads

The two standalone USB downloads contain no delivery wrapper or extra files:

```text
DEMO_FARM_AgGPS.zip
  AgGPS/Data/<Grower>/<Farm>/<Field>/...

DEMO_FARM_Shapefile.zip
  Shapefile/<Slug>_Bdy.shp
  Shapefile/<Slug>_Taipa.shp
```

Extract one ZIP and copy its only top-level folder to the USB root:

| Alternative | USB root must contain | Import2 source |
|---|---|---|
| `<Farm>_AgGPS.zip` | `E:\AgGPS\Data\...` | Non Pro 700 1 |
| `<Farm>_Shapefile.zip` | `E:\Shapefile\Plot12_Bdy.shp` | Shapefile |

The recommended method is to use the tractor's own USB: power off, remove it, leave its `.cn1` folder untouched, and copy `AgGPS` or `Shapefile` to the root beside `.cn1`. Never format the tractor USB, copy anything inside `.cn1`, copy the unopened ZIP, or place both formats on one stick. Return that same USB, power on, wait for the internal-copy message, and then open Import2.

If the tractor USB must not be connected to a computer, use a second FAT32 8–32 GB drive containing only `AgGPS` or only `Shapefile`. Let the Pro 700 copy it internally, then power off and reinsert the original `.cn1` USB before opening Import2. A drive without `.cn1` can leave Import2 without Grower/Farm/Field choices.

Import `*_Bdy` as **Boundary**, then `*_Taipa` as **Guidance / Line / Multiswath**. GPS auto-select works only when the vehicle is physically inside the closed Boundary polygon. One additional restart after importing can be normal.

`<Farm>_Mapas_lotes.zip` contains flat files such as `Plot12.jpg`, one rendered map per boundary-backed field. `<Farm>_paquete_completo.zip` contains both tractor ZIPs, the PDF, the image ZIP, `LEAME.txt`, and `INDICE_CAMPOS.txt`.

## Imagery attribution

Satellite-backed maps use Esri World Imagery and display the service attribution: `Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community`. Offline/no-satellite fallback maps do not display imagery attribution.

## Runtime Model

- FastAPI web app with a shared-password session
- One bounded conversion worker by default
- Filesystem-backed job state on `/data/jobs`
- Upload, archive-member, and extracted-size limits
- Protected artifacts and previews
- Automatic expiry and deletion after 24 hours by default
- Uploaded ZIPs and extracted working data deleted when processing finishes
- Read-only, non-root Docker runtime with a persistent jobs volume

This is a single-instance, single-operator deployment. Do not scale it horizontally or run multiple Uvicorn workers against the same jobs directory.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python process.py --help
```

The test suite builds synthetic 2D shapefiles programmatically. Do not commit customer AgGPS exports or generated farm artifacts.

## License

Copyright © 2026 Fran <jfrader@pm.me>. AgGPS Studio is free software licensed under the [GNU General Public License v3.0 or later](LICENSE).

## Project Layout

```text
app.py                 authenticated FastAPI app and job manager
process.py             CLI entry point
engine/                conversion, validation, maps, PDF, and tractor packaging
templates/             application HTML
static/                browser CSS and JavaScript
tests/                 engine and web tests
SPEC.md                USB, CRS, and map contract
DEPLOY.md              production deployment guide
```
