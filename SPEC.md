# Spec — AgGPS Studio

## Problem

Trimble FieldLevel / EZ-Office exports an `AgGPS/` tree. QGIS-style shapefile packs (3D POINTZ, extra DBF columns, folders named `Client__Farm__Field`) crash or stay invisible on a Case AFS Pro 700. The display only scans the USB root for a folder named exactly `AgGPS` or exactly `Shapefile`.

Drivers also need a paper map of the taipas (contour levees) because line features do not auto-select the field.

## Inputs

A `.zip` that contains, at any depth:

```
AgGPS/Data/<Grower>/<Farm>/<Field>/
  Boundary.shp / .shx / .dbf     # 2D polygon, WGS84 lon/lat
  LineFeature.shp / .shx / .dbf  # 2D polyline = taipas
  FieldLevel.xml                 # origin lat/lon/alt + survey x/y/z metres
  optional .pos, WM_Applied.xml
```

## Outputs

### A. Tractor ZIPs

```
<Farm>_AgGPS.zip
  AgGPS/Data/<Grower>/<Farm>/<Field>/… # original tree, copy AgGPS to USB root

<Farm>_Shapefile.zip
  Shapefile/
    <Slug>_Bdy.shp shx dbf             # 2D only, short ASCII names
    <Slug>_Taipa.shp shx dbf
```

Rules:

- Copy `.shp .shx .dbf` only (no `.prj` / `.cpg` required by Pro 700).
- Never include SurveyPoints or PolygonZ / PolylineZ / PointZ.
- Slug: alphanumeric, ≤10 chars (`Plot 12` → `Plot12`, `sample field` → `samplefiel`, `7` + farm `Demo Farm` → `DemoFa7`).
- The two alternatives are separate downloads. Each ZIP has exactly one ready-to-copy top-level folder, `AgGPS` or `Shapefile`, with no delivery wrapper or instruction files.
- Every delivered ZIP and PDF is prefixed with the ASCII-safe farm name, truncated to 48 characters. A single-client export with multiple farms uses the client name instead.
- One layout per stick: copy either the `AgGPS` or `Shapefile` folder to the USB root, never both.
- Survey groups with `LineFeature` but no `Boundary` remain only in the AgGPS alternative and are named in `LEAME.txt`; they are never exported as standalone Shapefile fields.
- `LEAME.txt` uses the uploaded Grower/Farm/Field names and USB slugs in its path examples.
- `LEAME.txt`, `INDICE_CAMPOS.txt`, and `<Farm>_Mapas_choferes.pdf` use the selected operator language: `es`, `en`, or `pt-BR`. The default is `es`.

### B. Standalone field images

`<Farm>_Mapas_lotes.zip` contains one flat `<Slug>.jpg` per boundary-backed field. Each image is the same rendered field map used by the PDF, including satellite imagery when available and the complete Boundary/taipa overlay. It contains no PDF and no subfolders.

### C. Driver PDF (A4 landscape)

1. Cover — grower/farm + full field index, USB filenames, areas, and date
2. Pro 700 load instructions (recommended same-stick copy, optional second-stick transfer, Import2)
3. Overview of all lotes
4. One page per lote — map + note `N taipas · ha · ΔZ mediano cm · cota min–max`

Map style for print: nadir satellite if reachable, else a dark paper fallback marked `sin satélite`. Taipa elevation uses the turbo colour ramp and the authoritative client Boundary is cyan. Every map states that the photo is background and the shapefile is never moved to fit it.

Field and overview rasters are optimized JPEG files. The longest edge is at most 1400 px and each PDF map image is at most 750 KiB. Portrait fields use a portrait map beside a vector statistics panel instead of shrinking into a landscape frame.

## Algorithms

**Discover** — walk extract for `Boundary.shp`; line-only survey groups are not tractor fields. Each discovered field must also contain `LineFeature.shp`. Grower/Farm/Field = three path segments under `Data/`.

**CRS** — AgGPS shapefiles are already WGS84 geographic. FieldLevel survey is a local ENU tangent plane:

```
lat = lat0 + n / R * 180/π
lon = lon0 + e / (R cos lat0) * 180/π
R = 6378137
```

**Area** — project boundary to ENU, shoelace, ÷ 10 000 → hectares.

**ΔZ per taipa set** — for each polyline, sample ~6 vertices, nearest survey Z (cap 80 m). Sort line medians. Median of adjacent differences in (0.1 cm, 150 cm) = typical contour interval.

**Satellite** — ESRI World Imagery MapServer export, bbox WGS84, JPEG. Request metadata with `f=json`, download its `href`, and place the image with the returned `extent`; ESRI may pad the requested bbox to match the output aspect ratio. Pixel dimensions remain proportional to ground metres. Satellite-backed maps visibly credit Esri and its imagery contributors; no-satellite fallbacks omit that attribution. Timeout 20 s. Failure is non-fatal and is identified in the PDF.

### D. Complete package

`<Farm>_paquete_completo.zip` contains the equivalently prefixed AgGPS, Shapefile, PDF, and field-image artifacts, plus `LEAME.txt` and `INDICE_CAMPOS.txt`.

## Pro 700 runtime (must stay in the generated instructions + PDF)

1. Extract `<Farm>_AgGPS.zip` **or** `<Farm>_Shapefile.zip` and copy its only top-level folder to the USB root. Never copy the unopened ZIP or both formats together.
2. Recommended: power off and remove the tractor's own USB. On a computer, leave `.cn1` untouched and copy the chosen folder to the USB root beside `.cn1`. Never format the USB or copy anything inside `.cn1`.
3. Return that same USB, power on, wait for the internal-copy message, then open Data Management → Import2.
4. Alternative: if the original USB must not be connected to a computer, put the chosen folder on a second FAT32 8–32 GB drive. Let the Pro 700 copy it internally, power off, and reinsert the original `.cn1` USB before opening Import2.
5. A drive without `.cn1` can leave Import2 without Grower/Farm/Field choices. One additional restart after import can be normal.
6. Import2 source:
   - AgGPS → Source `Non Pro 700 1`
   - Shapefile → Source `Shapefile`
7. `*_Bdy` as Data Type **Boundary**. `*_Taipa` as **Guidance / Multiswath / Line**.
8. Auto-select GPS only if the vehicle is physically inside that Boundary polygon. Taipa lines never select the field.

## Non-goals

- Writing `.cn1` natively (needs official AFS Mapping / SMS).
- Sending SurveyPoints to the display.
- Editing taipas / redesigning FieldLevel surfaces.

## Suggested next upgrades

- POSGAR 2007 / faja Gauss-Krüger toggle if a fleet runs projected coordinates.
- QR on each PDF page encoding Grower/Farm/Field + centroid.
- Batch two farms into one booklet.
- Optional QGIS-ready sibling zip (with `.prj`) for the office, kept separate from the tractor pack.
