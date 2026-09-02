# Changelog

## 0.4.2

### Fixed

- Linux desktop windows now use GTK over X11/XWayland to avoid Wayland protocol failures with portable bundles.

## 0.4.1

### Fixed

- Linux desktop bundles now use host-provided GTK, GLib, fontconfig, and WebKitGTK shared libraries instead of mixing Ubuntu build libraries with host libraries.

## 0.4.0

### Added

- `<Farm>_Mapas_lotes.zip` with one standalone rendered JPG per field.
- Portable Windows and Linux desktop apps with the existing AgGPS Studio interface embedded, persistent local jobs, and no server setup.
- Visible Esri and imagery-contributor attribution on satellite-backed field maps.

### Changed

- Replaced the combined `USB_Pro700.zip` download with separate `<Farm>_AgGPS.zip` and `<Farm>_Shapefile.zip` files that open directly to the ready-to-copy folder.
- `<Farm>_paquete_completo.zip` now contains both tractor ZIPs, the printable PDF, the field-image ZIP, and the localized instruction files.
- Every delivered ZIP and PDF now starts with the farm name, such as `DEMO_FARM_AgGPS.zip`.

## 0.3.0

### Added

- Spanish, English, and Brazilian Portuguese operator material, selectable in the web app and CLI with Spanish as the default.
- Localized `LEAME.txt`, `INDICE_CAMPOS.txt`, and `Mapas_choferes.pdf` while retaining stable artifact filenames.

### Changed

- Pro 700 instructions now recommend copying one inner layout beside the untouched `.cn1` folder on the tractor's own USB.
- The separate FAT32 transfer stick is documented as an alternative, including the required return to the `.cn1` USB before Import2.

## 0.2.0

### Added

- Authenticated FastAPI UI with background jobs, polling, previews, and protected downloads.
- Persistent filesystem job state, bounded processing, terminal-job expiry, and restart recovery.
- Upload and ZIP extraction limits with traversal, symlink, encryption, duplicate, and malformed-archive rejection.
- Docker Compose deployment with a non-root, read-only container and persistent jobs volume.
- Web, archive-safety, shapefile-validation, retention, and end-to-end engine tests.
- Complete two-column field index and adaptive portrait layouts in the printable driver booklet.

### Changed

- USB downloads now separate the two tractor import methods under `A_AgGPS/AgGPS` and `B_Shapefile/Shapefile`, matching the tractor-proven delivery package.
- AgGPS output preserves the original Boundary and LineFeature payload bytes while pruning SurveyPoints, Z shapefile families, `.prj`, and `.cpg` files.
- Uploaded ZIPs and extracted working data are deleted as soon as processing reaches a terminal state.
- The web container honors `HOST` and platform-provided `PORT` values.
- Driver maps now use compact JPEG previews, cyan client boundaries, explicit satellite fallback badges, and input-specific USB instructions.

### Fixed

- Prevented line-only survey groups from aborting otherwise valid multi-field AgGPS conversions.
- Prevented both tractor layouts from being placed together at the USB root.
- Prevented expired artifact and preview URLs from bypassing job expiry.
- Prevented hidden login and upload controls from being exposed by CSS.
- Added login-attempt throttling and removed the missing favicon console error.
- Corrected satellite alignment by rendering ESRI imagery with the extent returned by the export service instead of the requested bbox.
