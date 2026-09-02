---
name: aggps-pro700
description: Provides tractor packs (AgGPS + Shapefile layouts) and map/CRS guidance for Trimble FieldLevel or EZ-Office AgGPS zip exports into Case IH AFS Pro 700 USB packs. Printable maps delegated to the full AgGPS Studio app. Trigger on AgGPS, FieldLevel, EZ-Office, Pro 700, Puma, taipas, LineFeature, Boundary shapefile, Non Pro 700 1, or when the AgGPS Studio web app fails and a manual pack is needed.
metadata:
  type: workflow
  version: "1.0"
  domain: aggps-pro700
---

# AgGPS -> AFS Pro 700

Client survey bytes are law. Do not rewrite geometry to look cleaner or to fit a satellite photo. The pack that worked on a real Case IH Puma 210 + AFS Pro 700 was a **byte-identical 2D copy** of `Boundary` + `LineFeature`.

When the user attaches an `AgGPS.zip` (or `AgGPS-N.zip`), run the fallback converter in this skill rather than inventing a new layout.

```bash
python .agents/skills/aggps-pro700/scripts/convert_aggps.py INPUT.zip -o ./artifacts
```

This emits the CURRENT direct deliverables:
- <Farm>_AgGPS.zip   (extracts directly to AgGPS/ at root)
- <Farm>_Shapefile.zip (extracts directly to Shapefile/ at root)
- LEAME.txt and INDICE_CAMPOS.txt beside the ZIPs

Never run with --maps (explicitly errors; maps/PDF not implemented in fallback).

Do not reference old USB_Pro700/A_AgGPS/B_Shapefile wrappers. The converter matches production tractor contract exactly.

## Input

Typical tree (depth may vary):

```
AgGPS/Data/<Grower>/<Farm>/<Field>/
  Boundary.shp .shx .dbf     # 2D Polygon, WGS84 lon/lat
  LineFeature.shp .shx .dbf  # 2D Polyline = taipas (rice levees)
  FieldLevel.xml             # origin lat/lon/alt + survey x/y/z metres
  optional .pos, WM_Applied.xml
```

Tractor field = folder with **both** `Boundary.shp` and `LineFeature.shp`. Line-only folders (no Boundary) stay in the AgGPS tree only. They cannot auto-select and they crashed discovery when treated as fields.

## Output (direct-root, farm-prefixed; matches current tractor contract)

Standalone ZIPs open directly (no USB_Pro700, no A_/B_ wrappers ever created by fallback):

```
DEMO_FARM_AgGPS.zip
  AgGPS/Data/<Grower>/<Farm>/<Field>/...   # pruned full source (byte-identical permitted; line-only folders kept)

DEMO_FARM_Shapefile.zip
  Shapefile/<Slug>_Bdy.shp .shx .dbf
           <Slug>_Taipa.shp .shx .dbf

LEAME.txt
INDICE_CAMPOS.txt
```

- AgGPS tree: byte copy of permitted source, prunes SurveyPoints* families, Z shapefile families +sidecars, .prj, .cpg (per repo safety). Preserves line-only folders.
- Shapefile ZIP: ONLY 2D Boundary/LineFeature .shp/.shx/.dbf for boundary-backed fields (current slug rules).
- Slug = alphanumeric, <=10 chars. `Plot 12` -> `Plot12`. `Plot A` vs `PlotA` -> `PlotA` and `PlotA2`. Digit-only `7` + farm `Demo Farm` -> `DemoFa7`.
- LEAME/INDICE use exact names, placed beside the ZIPs.

## Do not

- Do not generate taipas. Copy `LineFeature`.
- Do not send 3D shapefiles or SurveyPoints to the display. That caused `SWException` / Picklist Title / null on this firmware.
- Do not mix `AgGPS` and `Shapefile` on one stick.
- Do not translate lon/lat so the photo looks nicer.
- Do not format the tractor USB (it holds `*.cn1`).
- Do not test farm B files while the tractor is parked in farm A.
- Do not invoke --maps (unsupported; fallback does not implement PDF or maps).

## Cab load (default)

Copy **one** inner folder onto the **same** stick that already has `*.cn1`, at the root, next to `.cn1`, never inside it.

```
E:\<something>.cn1\
E:\AgGPS\Data\<Grower>\<Farm>\<Field>\Boundary.shp
```

or

```
E:\<something>.cn1\
E:\Shapefile\<Slug>_Bdy.shp
E:\Shapefile\<Slug>_Taipa.shp
```

Power off -> copy on a PC -> same stick back -> power on -> wait "copied to internal storage" -> Data Management -> Import2.

- AgGPS path -> Source = **Non Pro 700 1**
- Shapefile path -> Source = **Shapefile**
- First `*_Bdy` as Data Type **Boundary**
- Then `*_Taipa` as **Guidance / Line / Multiswath**
- One field first. Auto-select only if the vehicle is physically inside that polygon.

Official Case **swap** (second stick with no `.cn1`, then put the original stick back) is the fallback when they refuse to touch the tractor USB. A stick left in the display without `.cn1` is not "just slower".

## Maps / PDF

Not implemented in this self-contained fallback converter (stdlib only, no satellite fetch, no matplotlib, no reportlab). Use the full AgGPS Studio app when maps are required. `--maps` will error explicitly. LEAME/INDICE and tractor ZIPs are produced.

## Validated operating pattern

The direct-root layouts above have been cab-tested on a Puma 210 with an AFS Pro 700. Start with one synthetic or operator-selected field; no farm or field requires a special file layout.
