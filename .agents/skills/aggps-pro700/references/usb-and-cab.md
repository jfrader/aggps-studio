# USB layout and cab procedure

## Why two layouts

The AFS Pro 700 only scans the **USB root** for a folder named exactly `AgGPS` or exactly `Shapefile`.

- `AgGPS` is the Trimble tree. Import2 source = **Non Pro 700 1**. Recommended when the zip already looks like EZ-Office / FieldLevel.
- `Shapefile` is flat `*_Bdy` + `*_Taipa`. Import2 source = **Shapefile**.

Current standalone downloads are direct `<Farm>_AgGPS.zip` / `<Farm>_Shapefile.zip` (open to AgGPS/ or Shapefile/ at root; never USB_Pro700/A_AgGPS/B_Shapefile wrappers). The tractor only scans USB root for exact `AgGPS` or `Shapefile`. (Older combined wrappers are historical.)

## Files that belong on the stick

| Keep | Never on tractor pack |
|---|---|
| `Boundary.shp .shx .dbf` (2D Polygon) | `SurveyPoints*` |
| `LineFeature.shp .shx .dbf` (2D Polyline) | PolygonZ / PolylineZ / PointZ |
| In A only: `FieldLevel.xml`, `.pos`, `WM_Applied.xml`, Data Dictionary, line-only folders | `.prj` / `.cpg` (office zip is fine separately) |

`.pos` / FieldLevel XML in the AgGPS tree did **not** recreate the picklist crash. 3D shapefiles and SurveyPoints did.

## Slug rules

```
strip non-alphanumeric
max 10 chars
if the result is only digits, prefix up to 6 alnum chars from the farm
on collision, append 2, 3, ... (2 C -> 2C, 2C -> 2C2)
```

Synthetic examples: `Plot 12` -> `Plot12`, `7` + `Demo Farm` -> `DemoFa7`.

## Line-only folders

If a folder has `LineFeature.shp` and no `Boundary.shp` (for example, `Survey North` or `Survey South`):

- Copy with the AgGPS tree (A).
- Do not invent a B slug.
- Do not put them on the PDF index.
- They cannot auto-select.

## `.cn1` - default vs swap

The display stores grower / farm / field / tasks / coverage in `*.cn1` on the stick that lives in the monitor. Import2 writes into that profile.

**Default (cab-tested):** put `AgGPS` or `Shapefile` on **that same stick**, root, next to `.cn1`. Do not format it. Power cycle. Wait for internal-copy popup. Import2. One extra restart after import is normal.

**Case official swap:** second stick has only the data folder. Display copies to internal memory. Put the original `.cn1` stick back before Import2.

If the stick in the display has no `.cn1`, Import2 may have no working Grower/Farm/Field. That is not "just slower".

The swap does not make taipas more accurate.

## Import order

1. One field.
2. Boundary first as Data Type **Boundary**.
3. Taipas second as **Guidance / Line / Multiswath**.
4. Vehicle must sit inside that polygon for auto-select.
5. Taipa lines never select the field.

## Multipart Boundary

If `Boundary.shp` is one record with two rings of the **same** winding, it is not a shapefile hole. Keep both rings in the USB. Printed area may use the largest ring until a surveyor says the inner one is an exclusion. A synthetic example can use a 12.5 ha outer ring and a 0.2 ha inner island.
