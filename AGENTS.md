# AGENTS.md — AgGPS Studio

Instructions for OpenCode, Grok, Codex, Claude, Cursor, or any coding agent working this repo.

## What this product is

A farm tool. User uploads a Trimble **AgGPS.zip** (FieldLevel / EZ-Office export). The app returns:

1. Separate `<Farm>_AgGPS.zip` and `<Farm>_Shapefile.zip` downloads for the **Case IH AFS Pro 700**
2. A printable **PDF** and a flat ZIP of taipa (rice levee) maps on nadir satellite imagery

The tractor trees already worked in a real Puma 210 cab. Do not alter their internal layout.

## Product rules you must not break

These caused a real `SWException #B / Null Pointer / Picklist Title` crash on the Pro 700 when we got them wrong.

- Pro 700 only scans the **USB root** for a folder named exactly `AgGPS` or exactly `Shapefile`.
- Tractor files are **2D only**: `Boundary.shp` = Polygon, `LineFeature.shp` = Polyline. Never ship PointZ / PolygonZ / PolylineZ / SurveyPoints to the display.
- Sidecars for the stick: `.shp .shx .dbf` only. `.prj` / `.cpg` are optional and can confuse older firmware.
- Short ASCII slugs: `Plot 12` → `Plot12_Bdy` + `Plot12_Taipa`. No `__`, no spaces on the Shapefile names.
- Copy **one** layout per stick, never both `AgGPS` and `Shapefile` together.
- Every delivered ZIP and PDF uses the ASCII-safe farm name as its prefix. The tractor folders inside remain exactly `AgGPS` and `Shapefile`.
- Standalone downloads end in `_AgGPS.zip` and `_Shapefile.zip`. Each must open directly to its one ready-to-copy folder; never restore the `USB_Pro700/A_AgGPS` or `B_Shapefile` delivery wrappers.
- `<Farm>_Mapas_lotes.zip` is flat and contains one rendered `<Slug>.jpg` per boundary-backed field. It must not contain the PDF or subfolders.
- Recommended transfer: copy the chosen inner folder to the tractor's own USB root beside the untouched `.cn1` folder. Never format that USB or copy files inside `.cn1`.
- A second FAT32 stick is an alternative only. Reinsert the original `.cn1` USB before Import2; a stick without `.cn1` can leave farm entities unavailable.
- Import order: Boundary first (Data Type = Boundary), taipas second (Guidance / Line / Multiswath).
- GPS auto-select uses the **closed outer polygon**, never the taipa lines.
- Maps must be **nadir / top-down**. Plot with ground aspect `1 / cos(lat)` and request the satellite image with pixel size proportional to metres. `ax.set_aspect("equal")` on raw lon/lat degrees makes the field look angled and the overlay miss. That bug already shipped once — do not regress it.
- FieldLevel survey is local ENU metres around `origin lat/lon/alt` in `FieldLevel.xml`. Shapefiles in this export are WGS84 lon/lat. Use `engine/geo.py`.

Canonical domain spec: `SPEC.md`.

If the app is unavailable and a manual tractor pack is needed, use the
repository fallback skill at `.agents/skills/aggps-pro700/SKILL.md` instead of
inventing a new USB layout.

## Repo map

```
app.py                 authenticated FastAPI UI + filesystem job manager
desktop.py             pywebview + embedded server desktop entry (--smoke-test, --version, desktop_mode)
process.py             CLI entry
engine/pipeline.py     zip → tractor ZIPs + PDF + field images
engine/discover.py     find Grower/Farm/Field under AgGPS/Data
engine/pack.py         tractor trees + LEAME.txt
engine/analyze.py      ha, ΔZ, line colors
engine/render.py       nadir maps (dark, cyan boundary, scale bar)
engine/basemap.py      ESRI World Imagery
engine/pdfmake.py      A4 landscape driver booklet
engine/fieldlevel.py   origin + survey_points
engine/shpio.py        shapefile read/copy, no pyshp
templates/index.html   upload UI
aggps_studio.spec      PyInstaller onedir spec (windowed, datas for templates/static)
build_desktop.py       stdlib cross-platform bundler (clean, PyInstaller, BUNDLE_README, zip)
requirements-build-desktop.txt  PyInstaller 6.22.2 + desktop runtime
tests/test_packaging.py  zip structure, exe, resources, no-customer-inputs checks
SPEC.md                USB + CRS + ΔZ contract
DEPLOY.md              where/how to host
```

## How to work

1. Read `SPEC.md` before changing pack or render.
2. Keep the engine importable without a web server: `from engine.pipeline import process_aggps_zip`.
3. Prefer small diffs. Do not rewrite `engine/` unless the task needs it.
4. After pack/render/geo changes, run:

```bash
python -m pytest -q
python process.py --help
```

For desktop/packaging changes keep green the packaging tests and produce the bundles (see "Tests the agent must keep green").

If an `AgGPS.zip` is available:

```bash
python process.py path/to/AgGPS.zip --out /tmp/aggps_out --no-sat
```

Sanity check the standalone downloads:

- `<Farm>_AgGPS.zip` has only `AgGPS/Data/<Grower>/<Farm>/<Field>/Boundary.shp` at its root
- `<Farm>_Shapefile.zip` has only `Shapefile/<Slug>_Bdy.shp` and `<Slug>_Taipa.shp` at its root
- `<Farm>_Mapas_lotes.zip` has flat `<Slug>.jpg` entries
- no `SurveyPoints*`

5. `LEAME.txt`, `INDICE_CAMPOS.txt`, and the PDF support `es`, `en`, and Brazilian Portuguese (`pt-BR`); Spanish is the default. Keep artifact suffixes stable and preserve the farm prefix. Code and agent docs stay in English.
6. Do not add SurveyPoints to either tractor ZIP “for completeness”.
7. Keep the production web app on FastAPI and keep `engine/` usable without it.

## Production baseline

The Docker deployment is an authenticated, single-instance service:

- Shared-password signed sessions; all authenticated operators can access all retained jobs.
- One bounded worker by default. Do not run multiple containers or Uvicorn workers against one jobs volume.
- Upload, archive-member, and extracted-size limits are enforced before conversion.
- Job state and terminal artifacts persist on `/data/jobs`; uploaded and extracted working data is removed after processing.
- Terminal artifacts expire automatically and all artifact routes enforce the same TTL.
- Satellite imagery is optional and the paper-map fallback must remain functional.

Future multi-user auth, cached satellite tiles, branding, or a QGIS sibling package are separate product changes. A QGIS package must never be mixed into the tractor payload.

## Tests the agent must keep green

`tests/test_engine.py` covers ENU↔WGS84, slugs, USB layout rules. Add a fixture zip under `tests/fixtures/` only if it is tiny (<200 KB) and contains fake 2D Boundary + LineFeature. Do not commit customer AgGPS dumps.

For desktop packaging work:
- `python -m pytest -q tests/test_desktop.py tests/test_packaging.py`
- `python -m pip install -r requirements-build-desktop.txt`
- `python build_desktop.py` (builds in platform temp dir via gettempdir(), produces zips, self-checks)
- Then: run the frozen exe from the onedir --version and --smoke-test (no GUI).

Do not run heavy unrelated tests or launch GUI during packaging verification. Fallback skill at `.agents/skills/aggps-pro700/SKILL.md` remains registered and is never removed.

## Deploy targets (pick one)

Recommended first ship: **Docker on a VPS or Fly.io / Railway**.

- Dockerfile is the source of truth for runtime.
- Need outbound HTTPS for ESRI imagery (optional).
- Writable volume at `/data/jobs`.
- Memory: 1–2 GB. Matplotlib + a multi-field zip can peak well above 512 MB.
- Set `MPLCONFIGDIR=/tmp/mpl`.

Details in `DEPLOY.md`.

## Tone when editing copy

Drivers print the PDF and take it in the cab. Use short sentences and no GIS jargon. Keep each translation operationally equivalent to: “Boundary = límite. Taipas = líneas. Auto-select solo con el polígono.” Never restore swap-only instructions: the tractor's own USB is the recommended path and the second stick is the alternative.
