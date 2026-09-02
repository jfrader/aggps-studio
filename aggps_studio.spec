# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for AgGPS Studio onedir desktop app (Windows x64 / Linux x64).

- onedir layout for inspectable portable bundle
- console=False (windowed) for normal GUI launcher (no console window)
- templates/ and static/ bundled via datas at bundle root
- engine/ collected as package (bytecode, no raw source shipping)
- hiddenimports/hooks ONLY for actually required modules (uvicorn sockets mode,
  matplotlib Agg, reportlab, Pillow, pywebview platform, fastapi/starlette static)
- excludes test/dev to keep clean
- version.py collected via module analysis (no top-level source .py copy)
- No customer inputs, jobs/, caches, or project source included in bundle
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

ROOT = Path.cwd()

# Only bundle the runtime web assets + engine code (via imports). No source tree.
datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "static"), "static"),
]

# Hidden imports: add strictly as needed after analysis failures.
# Start lean; PyInstaller + collect_submodules handle most std + our engine.
hiddenimports: list[str] = [
    # desktop server path (uvicorn.Server.run(sockets=) + imports inside)
    "uvicorn",
    "uvicorn.config",
    "uvicorn.server",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.logging",
    # fastapi app + static files mount (used at runtime in frozen)
    "fastapi",
    "fastapi.staticfiles",
    "starlette",
    "starlette.staticfiles",
    "starlette.responses",
    # engine package (all modules pulled by pipeline at import time)
    "engine",
]
hiddenimports += collect_submodules("engine")

# matplotlib (render sets Agg before pyplot; needed for non-GUI smoke + PDF maps)
hiddenimports += [
    "matplotlib",
    "matplotlib.backends.backend_agg",
    "matplotlib.pyplot",
    "matplotlib.figure",
    "matplotlib.collections",
    "matplotlib.colors",
]

# reportlab (pdfmake)
hiddenimports += [
    "reportlab",
    "reportlab.pdfgen",
    "reportlab.pdfgen.canvas",
    "reportlab.lib",
    "reportlab.lib.pagesizes",
    "reportlab.lib.units",
    "reportlab.lib.utils",
    "reportlab.lib.colors",
    "reportlab.pdfbase",
    "reportlab.pdfbase.pdfmetrics",
]

# Pillow (basemap + images)
hiddenimports += [
    "PIL",
    "PIL.Image",
    "PIL._imaging",
]

# pywebview (only imported in GUI path; include platform bits for collection)
hiddenimports += [
    "webview",
    "webview.platforms",
]
if sys.platform.startswith("win"):
    hiddenimports += [
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
    ]
elif sys.platform.startswith("linux"):
    hiddenimports += [
        "webview.platforms.gtk",
        "gi",
        "gi.repository",
        "gi.repository.Gtk",
        "gi.repository.WebKit2",
    ]

# platformdirs (used early for MPLCONFIGDIR + jobs)
hiddenimports += ["platformdirs"]

# Keep bundle small and clean: exclude dev/test/source not required at runtime.
excludes = [
    "tests",
    "pytest",
    "setuptools",
    "wheel",
    "pip",
    "tkinter",
    "_tkinter",
    "IPython",
    "jupyter",
    # Linux ships only the GTK backend; avoid accidental Qt fallback and bloat
    # when a developer build environment also has Qt bindings installed.
    "webview.platforms.qt",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
]

a = Analysis(
    ["desktop.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Keep the host GUI stack internally consistent. Bundling Ubuntu's GTK/GLib
# libraries while loading WebKitGTK from another distro causes ABI failures.
if sys.platform.startswith("linux"):
    a.exclude_system_libraries()

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgGPS Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # reproducible + avoid AV false positives on some CI
    console=False,  # --windowed: no console for normal GUI launcher
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AgGPS Studio",
)
