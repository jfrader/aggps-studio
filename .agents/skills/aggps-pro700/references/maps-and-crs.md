# CRS, area, delta Z, satellite

## Coordinates

AgGPS `Boundary` / `LineFeature` from FieldLevel / EZ-Office on this fleet are already **WGS84 lon/lat**.

`FieldLevel.xml` survey is local ENU metres around:

```xml
<origin lat='...' lon='...' alt='...'>
```

```
lat = lat0 + north / R * 180/pi
lon = lon0 + east / (R * cos(lat0)) * 180/pi
R = 6378137
```

Sanity check: convert XML boundary points and compare to `Boundary.shp` vertices. A small metre-scale mismatch can reflect measurement precision; a 100 m+ gap means the wrong origin or a projected shapefile. Stop and ask rather than guessing POSGAR / Gauss-Kruger unless the user identifies that CRS.

`.pos` filenames often encode the origin (synthetic example: `34.56789E12.34567N100H.pos`).

## Area

Project the chosen ring to ENU with `ll_to_enu`, shoelace, divide by 10 000 -> hectares. For multipart same-winding rings, default printed area = largest ring.

## Taipa delta Z (PDF only)

Do not put Z on the tractor shapefile.

From `FieldLevel.xml` `<survey_points>` (x,y,z metres):

1. Sample about six vertices per `LineFeature` part.
2. Convert vertex lon/lat to ENU with the same origin.
3. Nearest survey Z within 80 m.
4. Median Z per line. Sort lines. Median of adjacent differences in (0.1 cm, 150 cm) = typical interval.

Color the printed lines by that median Z. The Puma follows the 2D line, not this color.

## Satellite - the bug that looked like a bad survey

Esri World Imagery export:

```
bboxSR=4326  imageSR=4326  size=W,H  f=json
```

If `W,H` is computed from **ground metres** (`delta lon * 111320 * cos(lat)`), Esri keeps the requested longitude span and **pads latitude** so the image aspect matches the pixel aspect in degrees.

When plotting with the requested bbox, the export service may add substantial north/south padding while preserving the longitude span. The crop shape can match the polygon but place the overlay against the wrong visible background.

**Fix:** download `href` from `f=json` and `imshow(..., extent=(returned xmin, xmax, ymin, ymax), origin="upper")`. Keep `ax.set_aspect(1/cos(lat))` for nadir.

Alternatives: request `size` from degree aspect `(delta lon/delta lat)` when `imageSR=4326`; or plot image + vectors in EPSG:3857 with `aspect='equal'`.

Do not shift Boundary / LineFeature to match the photo. After the extent fix, 10-20 m leftover vs photo year / berm is normal.

## PDF

- A4 landscape. Spanish.
- Cover index of every tractor field (not a 15-row cut).
- Overview + one page per lote.
- Embed JPEG quality ~78, long side <=1400 px. Keep large multi-field books compact rather than embedding full-size PNGs.
- Footer: cyan = client GPS polygon. Photo is backdrop. Shapefile is not moved to fit the image.
- Offline fallback when Esri fails - badge `SIN SATELITE`, still print the lines.
- Skinny lots: keep geographic aspect; put stats in a side column instead of stretching the field.
