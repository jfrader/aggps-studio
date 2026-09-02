# Pyodide PWA feasibility

## Decision

The conversion engine can run client-side in a Web Worker with Pyodide. A
bounded PWA prototype is justified, but it should not replace the current
FastAPI or desktop distributions until realistic archive-scale and iOS Safari
acceptance tests pass.

The browser architecture keeps uploaded farm data local. Satellite mode is the
exception because it sends the requested bounding box to Esri World Imagery.

## Verified scope

An exploratory Chromium harness loaded the unchanged `engine/` package into
Pyodide 314.0.6 and ran `process_aggps_zip()` against the programmatic one-field
fixture used by `tests/test_engine.py`. Processing ran in a Web Worker with
satellite imagery disabled for the native-output comparison.

The same worker separately exercised `engine.basemap.fetch_satellite()` against
a valid World Imagery extent. The existing synchronous `requests` path worked
inside the worker and decoded the returned JPEG.

The harness also completed with every runtime asset and Python wheel served
from the same local origin. This proves that the runtime dependency set can be
self-hosted for a service-worker-backed installation; it was not a complete
offline/disconnected PWA test.

## Compatibility

| Dependency | Desktop pin | Browser result | Required browser treatment |
|---|---:|---:|---|
| Python | 3.13 | 3.14.2 | Use the Python version embedded by the selected Pyodide release. |
| Matplotlib | 3.11.1 | 3.10.8 | Use Pyodide's compiled package and keep visual golden tests. |
| Pillow | 12.3.0 | 12.2.0 | Use Pyodide's compiled package and keep image comparisons. |
| ReportLab | 5.0.1 | 5.0.1 | Self-host the pure-Python wheel and install it with `micropip`. |
| Requests | 2.34.2 | 2.33.1 | Use Pyodide's package; browser CORS still governs requests. |

No FastAPI, Uvicorn, pywebview, database, subprocess, or native GIS library is
needed by the browser worker. The engine's `pathlib`, `zipfile`, `shutil`, and
binary shapefile operations worked against Pyodide's in-memory filesystem.

## Output comparison

The browser result preserved the existing output contract:

- Artifact names and the farm-derived prefix matched the native result.
- Every uncompressed `.shp`, `.shx`, and `.dbf` tractor payload was
  byte-identical to native output.
- `LEAME.txt` and `INDICE_CAMPOS.txt` were byte-identical.
- The downloaded complete bundle passed ZIP CRC validation.
- Extracted PDF text was identical after ignoring the expected printed
  timestamp.
- The standalone browser map remained `1300 x 1061` pixels. Compared with the
  native image, 95.6789% of pixels were exact and the mean absolute channel
  difference was 0.0945 on a 0-255 scale.

Whole ZIP, PDF, and JPEG hashes are not identical. ZIP metadata and compression
differ between runtimes, the PDF contains its generation timestamp, and the
browser uses slightly older Matplotlib and Pillow builds. Acceptance should
compare tractor members, document semantics, dimensions, and visual golden
thresholds rather than container hashes.

## Measured cost

These numbers describe one development-machine Chromium session and the tiny
one-field synthetic fixture. They are not capacity guarantees.

| Measurement | Result |
|---|---:|
| Native processing | 142 ms |
| Browser processing | 3.2-3.6 s |
| Browser slowdown for this fixture | About 24x |
| Cached browser startup plus processing | About 6.4 s |
| Esri satellite fetch and decode | 4.4-6.4 s |
| Self-hosted cold runtime transfer | About 29.3 MB |
| Self-hosted warm-cache transfer | 7.2 KB |
| WASM heap after processing | About 108 MiB |

The current package set is practical for an installed PWA cache, but the heap
baseline and processing slowdown make mobile scale the main unknown.

## Risks and conditions

The PWA remains conditional on these acceptance results:

1. Process realistic synthetic archives on the oldest supported iPhone and
   iPad without Safari terminating or reloading the tab.
2. Establish acceptable duration and peak-memory limits for small, typical,
   and worst-case field and point counts.
3. Preserve the tractor ZIP contract exactly and pass PDF/JPEG visual golden
   comparisons across every supported language.
4. Complete a disconnected second run after installation, including cache
   version upgrades and recovery from Safari cache eviction.
5. Validate file import, progress, cancellation, background/foreground
   transitions, and bundle download through the iOS Files interface.

A browser cannot copy directly to a tractor USB or choose arbitrary filesystem
destinations on every platform. The supported mobile workflow would download
the completed bundle to Files. Offline processing must omit satellite imagery
unless the imagery was obtained beforehand.

Esri currently permits the worker requests through CORS, but that is an
external service behavior rather than an application guarantee. The existing
paper-map fallback must remain available.

## Optimization priorities

Optimize only after collecting representative archive profiles. The most
promising changes are:

1. Keep one worker and Pyodide runtime warm between conversions instead of
   reloading roughly 29 MB for each job.
2. Self-host immutable runtime files and precache them with a versioned service
   worker. Install ReportLab from the local wheel instead of querying PyPI.
3. Separate tractor ZIP creation from map and PDF rendering in the browser
   workflow. Pure conversion can finish first while the expensive optional
   rendering stage continues.
4. Load Matplotlib and ReportLab only when map/PDF artifacts are requested.
5. Transfer uploaded and completed archive buffers rather than copying them
   repeatedly between the main thread and worker.
6. Implement cancellation by terminating and recreating the worker, then clear
   its temporary filesystem after each job.

Replacing Matplotlib or ReportLab with Canvas, SVG, or JavaScript PDF tooling
could substantially reduce startup and processing cost, but it would duplicate
rendering logic and create the highest risk of changing validated output
layouts. Treat that as a later measured optimization, not the initial PWA
port.

## Recommended next experiment

Build a minimal installable PWA around the existing engine and a dedicated Web
Worker. Exercise generated fixtures at increasing field and point counts, then
run the same suite on physical iOS Safari. Keep the current production web and
desktop applications unchanged until those gates pass.
