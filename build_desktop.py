#!/usr/bin/env python3
"""Cross-platform build helper for AgGPS Studio desktop onedir bundles.

- Cleans using stdlib only.
- Invokes pinned PyInstaller via the maintainable .spec.
- Uses platform temp (Path(tempfile.gettempdir())) for all PyInstaller workpath/distpath artifacts (reproducible, no cwd pollution).
- Generates embedded third-party license notices from the build environment.
- Injects BUNDLE_README.txt, LICENSE.txt, and THIRD_PARTY_NOTICES.txt inside the onedir.
- Zips the *entire* onedir folder (exactly one top-level "AgGPS Studio/" folder).
- Copies finalized onedir to repo dist/AgGPS Studio/ (for consistent CI $GITHUB_WORKSPACE/dist/AgGPS Studio/...)
  alongside the ZIP; PyInstaller work stays in platform temp dir.
- Produces: dist/aggps-studio-<version>-*.zip + dist/AgGPS Studio/ onedir
- Self-checks (stdlib) the zip + the exact final onedir bundle.

Run after: pip install -r requirements-build-desktop.txt
Local build (recommended): python build_desktop.py
Do not launch GUI from here; --smoke-test and --version are safe.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


THIRD_PARTY_NOTICES_FILENAME = "THIRD_PARTY_NOTICES.txt"
REQUIRED_NOTICE_PACKAGES = {
    "fastapi",
    "itsdangerous",
    "matplotlib",
    "pillow",
    "platformdirs",
    "python-multipart",
    "pywebview",
    "reportlab",
    "requests",
    "uvicorn",
}


def _get_version() -> str:
    """Read APP_VERSION from version.py without executing module code."""
    vp = Path(__file__).resolve().parent / "version.py"
    for raw in vp.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("APP_VERSION"):
            # APP_VERSION = "0.4.0"
            val = line.split("=", 1)[1].strip()
            return val.strip("\"' ")
    raise RuntimeError("APP_VERSION not found in version.py")


def _generate_third_party_notices(root: Path) -> Path:
    """Generate a sorted, text-only license inventory from the build environment."""
    notices_path = root / THIRD_PARTY_NOTICES_FILENAME
    notices_path.unlink(missing_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "piplicenses",
        "--from=all",
        "--order=name",
        "--format=plain-vertical",
        "--with-license-file",
        "--no-license-path",
        "--with-notice-file",
        "--output-file",
        str(notices_path),
    ]
    print(f"[build] generating {THIRD_PARTY_NOTICES_FILENAME}")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=root)

    if not notices_path.is_file():
        raise RuntimeError("pip-licenses did not create the third-party notices file")
    _validate_third_party_notices(notices_path)
    return notices_path


def _validate_third_party_notices(notices_path: Path) -> None:
    """Reject empty inventories and inventories missing direct runtime packages."""
    notices = notices_path.read_text(encoding="utf-8")
    if len(notices.strip()) < 1_000:
        raise RuntimeError("third-party notices are unexpectedly empty or incomplete")

    notice_lines = {line.strip().casefold() for line in notices.splitlines()}
    missing = sorted(REQUIRED_NOTICE_PACKAGES - notice_lines)
    if missing:
        raise RuntimeError(
            "third-party notices are missing bundled runtime packages: "
            + ", ".join(missing)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="AgGPS Studio desktop bundler")
    parser.add_argument("--verify", action="store_true", help="verify existing dist/ bundle (exe --version/--smoke exact markers + ZIP layout); cross-platform, no heredoc needed for CI")
    args = parser.parse_args()

    if args.verify:
        _verify_bundle()
        return

    root = Path(__file__).resolve().parent
    version = _get_version()
    sysname = platform.system().lower()
    if sysname.startswith("win"):
        plat = "windows-x64"
        exe_basename = "AgGPS Studio.exe"
    elif sysname == "linux":
        plat = "linux-x64"
        exe_basename = "AgGPS Studio"
    else:
        raise RuntimeError(f"Unsupported platform for desktop packaging: {sysname} (only windows, linux)")

    zip_name = f"aggps-studio-{version}-{plat}.zip"
    print(f"[build] target: {zip_name} (plat={plat})")
    notices_path = _generate_third_party_notices(root)

    # All PyInstaller artifacts in platform temp (as required, cross-platform). Final zip lands in ./dist
    tmp_base = Path(tempfile.gettempdir()) / f"aggps-desktop-build-{plat}-{version}"
    if tmp_base.exists():
        shutil.rmtree(tmp_base, ignore_errors=True)
    tmp_base.mkdir(parents=True, exist_ok=True)

    workpath = tmp_base / "work"
    distpath = tmp_base / "dist"
    workpath.mkdir(parents=True)
    distpath.mkdir(parents=True)

    spec_file = root / "aggps_studio.spec"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--workpath",
        str(workpath),
        "--distpath",
        str(distpath),
        str(spec_file),
    ]
    print(f"[build] running PyInstaller (cwd={root})")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=root)

    bundle_dir = distpath / "AgGPS Studio"
    if not bundle_dir.is_dir():
        raise RuntimeError(f"PyInstaller onedir not found at {bundle_dir}")

    # Inject small README inside the bundle (launch + Linux caveat, no false static claim)
    bundle_readme = f"""AgGPS Studio {version} ({plat})

Portable onedir desktop application for AgGPS Studio.
Copyright (C) 2026 Fran <jfrader@pm.me>.
Licensed under the GNU General Public License v3.0 or later; see LICENSE.txt.
Bundled third-party software and license texts are listed in THIRD_PARTY_NOTICES.txt.

LAUNCH
------
Windows: Double-click "AgGPS Studio.exe" inside this folder.
         Or from terminal: "AgGPS Studio.exe" --help

Linux:   chmod +x "AgGPS Studio"
         ./"AgGPS Studio" --help

The normal launcher disables the console window (--windowed).

WINDOWS RUNTIME
---------------
Edge WebView2 Evergreen runtime is present on most modern Windows systems.
If the GUI fails with a webview error, install the Evergreen bootstrapper from
the official Microsoft page:
  https://developer.microsoft.com/en-us/microsoft-edge/webview2/
Do not assume it is bundled in this package.

LINUX RUNTIME CAVEAT
--------------------
This bundle is portable application files. It does NOT bundle host GTK/WebKit
shared libraries. The embedded browser (pywebview) requires system WebKitGTK + GTK.

Exact supported command (Ubuntu 24.04+ / Debian testing+):
  sudo apt-get update
  sudo apt-get install -y gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 gir1.2-gtk-3.0

Do NOT run on systems without these packages; the GUI will fail with a clear
message containing the install hint. Satellite and PDF features work headless.

SMOKE / VERSION (verification)
------------------------------
The packaged executable supports:
  "AgGPS Studio" --version
  "AgGPS Studio" --smoke-test
  "AgGPS Studio" --gui-smoke-test   (Linux under xvfb and Windows directly in CI; probes real native backend init + auto-closing window)

--smoke-test is server-only (never imports webview). --gui-smoke-test exercises the packaged GTK/Edge path and exits 0 only on successful backend initialization.
(Verification only writes markers when AGGPS_DESKTOP_VERIFY_DIR is exported.)

BUILD
-----
From a clean checkout:
  python -m pip install -r requirements-build-desktop.txt
  python build_desktop.py

Zips + unpacked onedir (dist/AgGPS Studio/) written to repo dist/. PyI work in platform temp dir.
See AGENTS.md and README.md for details.
"""
    (bundle_dir / "BUNDLE_README.txt").write_text(bundle_readme, encoding="utf-8")
    shutil.copy2(root / "LICENSE", bundle_dir / "LICENSE.txt")
    shutil.copy2(notices_path, bundle_dir / THIRD_PARTY_NOTICES_FILENAME)

    # Ensure output dir
    out_dir = root / "dist"
    out_dir.mkdir(exist_ok=True)
    zip_path = out_dir / zip_name
    if zip_path.exists():
        zip_path.unlink()

    print(f"[build] creating zip from onedir: {bundle_dir} -> {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(bundle_dir.rglob("*")):
            if p.is_file():
                arc = p.relative_to(bundle_dir.parent)  # "AgGPS Studio/..."
                zf.write(p, arc)

    # Self-check (stdlib asserts) - also exercised by tests/test_packaging.py
    print("[build] verifying zip contents")
    with zipfile.ZipFile(zip_path) as zf:
        nl = zf.namelist()
        tops = {n.split("/")[0] for n in nl if n}
        assert len(tops) == 1, f"ZIP must contain exactly one top-level folder, got {tops}"
        assert "AgGPS Studio" in tops, f"top folder must be 'AgGPS Studio', got {tops}"

        # executable
        if "windows" in plat:
            assert any(n.endswith("AgGPS Studio.exe") for n in nl), "missing windows exe"
        else:
            # the executable itself (no .exe) directly under the folder
            assert any(n == "AgGPS Studio/AgGPS Studio" for n in nl), "missing linux executable"

        # templates + static present in frozen bundle layout
        assert any("templates/index.html" in n for n in nl), "templates missing from bundle"
        assert any("static/app.js" in n for n in nl), "static missing from bundle"
        assert "AgGPS Studio/BUNDLE_README.txt" in nl, "bundle README missing"
        assert THIRD_PARTY_NOTICES_FILENAME in zf.read(
            "AgGPS Studio/BUNDLE_README.txt"
        ).decode("utf-8"), "bundle README does not reference third-party notices"
        assert "AgGPS Studio/LICENSE.txt" in nl, "license missing from bundle"
        assert (
            f"AgGPS Studio/{THIRD_PARTY_NOTICES_FILENAME}" in nl
        ), "third-party notices missing from bundle"
        assert (
            zf.getinfo(f"AgGPS Studio/{THIRD_PARTY_NOTICES_FILENAME}").file_size
            >= 1_000
        ), "third-party notices are unexpectedly small"

        # no customer inputs, jobs, caches, or stray source
        forbidden_substr = [
            "jobs/", "_jobs/", "input.zip", "AgGPS.zip",  # customer-like
            ".git/", "tests/", "test_packaging",  # dev
            "/__pycache__/",  # stray (engine pyc ok inside package dirs)
        ]
        bad = [n for n in nl if any(fs in n for fs in forbidden_substr)]
        assert not bad, f"forbidden content found in runtime zip: {bad[:5]}"

    # Contract for CI: copy the finalized onedir bundle to repository dist/AgGPS Studio/
    # (alongside the ZIP). PyInstaller intermediates stay in platform temp dir.
    out_dir = root / "dist"
    final_bundle_dir = out_dir / "AgGPS Studio"
    if final_bundle_dir.exists():
        shutil.rmtree(final_bundle_dir, ignore_errors=True)
    shutil.copytree(bundle_dir, final_bundle_dir)
    print(f"[build] copied finalized bundle to {final_bundle_dir}")

    # Self-check the exact final onedir bundle (not just zip)
    print("[build] verifying final repo onedir bundle")
    final_exe = final_bundle_dir / ("AgGPS Studio.exe" if "windows" in plat else "AgGPS Studio")
    assert final_exe.exists(), f"final bundle missing exe: {final_exe}"
    assert (final_bundle_dir / "templates" / "index.html").exists() or (final_bundle_dir / "_internal" / "templates" / "index.html").exists(), "templates missing in final bundle"
    assert (final_bundle_dir / "static" / "app.js").exists() or (final_bundle_dir / "_internal" / "static" / "app.js").exists(), "static missing in final bundle"
    assert THIRD_PARTY_NOTICES_FILENAME in (
        final_bundle_dir / "BUNDLE_README.txt"
    ).read_text(encoding="utf-8"), "bundle README does not reference third-party notices"
    assert (final_bundle_dir / "LICENSE.txt").exists(), "license missing in final bundle"
    assert (
        final_bundle_dir / THIRD_PARTY_NOTICES_FILENAME
    ).exists(), "third-party notices missing in final bundle"
    # no forbidden in the copied bundle tree
    for p in final_bundle_dir.rglob("*"):
        if p.is_file():
            rp = str(p.relative_to(final_bundle_dir))
            assert not any(fs in rp for fs in ["jobs/", "_jobs/", ".git/", "tests/"]), f"forbidden in final bundle: {rp}"

    print(f"[build] OK: {zip_path} ({zip_path.stat().st_size} bytes) + bundle at {final_bundle_dir}")
    # tmp_base left for inspection; CI can clean workspace
    print("[build] complete (tmp artifacts in", tmp_base, ")")


def _verify_bundle() -> None:
    """Cross-platform stdlib verification of the finalized repo dist/ bundle.
    - Locates dist/AgGPS Studio/ onedir (the one copied by build for CI contract)
    - Runs the packaged executable --version and --smoke-test from a *clean* temp cwd, passing AGGPS_DESKTOP_VERIFY_DIR
    - Asserts exact marker files written only to the verify dir (== "0.4.0", "OK"); no litter in caller cwd
    - Asserts exit codes == 0 (no || true fallbacks)
    - Performs ZIP member inspection for exactly one top-level folder, exe, templates/static, no forbidden content
    - Also sanity checks the onedir bundle itself
    Intended to be called from CI as: python build_desktop.py --verify
    Works for both Windows and Linux artifacts on their respective runners.
    """
    root = Path(__file__).resolve().parent
    expected_version = _get_version()
    bundle_dir = root / "dist" / "AgGPS Studio"
    if not bundle_dir.is_dir():
        raise AssertionError(f"final onedir bundle not found at {bundle_dir} (run build first)")

    # determine exe (support the copied layout)
    if os.name == "nt" or sys.platform.startswith("win"):
        exe = bundle_dir / "AgGPS Studio.exe"
    else:
        exe = bundle_dir / "AgGPS Studio"
    if not exe.exists():
        raise AssertionError(f"packaged executable not found: {exe}")

    import tempfile
    # Run from clean temp cwd to test markers + process start (handles windowed case)
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        env = os.environ.copy()
        env["AGGPS_DESKTOP_VERIFY_DIR"] = str(td)
        # --version
        res = subprocess.run(
            [str(exe), "--version"],
            cwd=td,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode != 0:
            raise AssertionError(f"--version failed rc={res.returncode} stdout={res.stdout!r} stderr={res.stderr!r}")
        ver_marker = (td / ".aggps-version").read_text(encoding="utf-8").strip()
        if ver_marker != expected_version:
            raise AssertionError(
                f"expected version marker {expected_version!r} but got {ver_marker!r}"
            )
        # --smoke-test
        res = subprocess.run(
            [str(exe), "--smoke-test"],
            cwd=td,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode != 0:
            raise AssertionError(f"--smoke-test failed rc={res.returncode} stdout={res.stdout!r} stderr={res.stderr!r}")
        smoke_marker = (td / ".aggps-smoke-ok").read_text(encoding="utf-8").strip()
        if smoke_marker != "OK":
            raise AssertionError(f"expected smoke marker 'OK' but got {smoke_marker!r}")
        # assert exact marker files present only in verify dir (not polluting caller cwd)
        assert (td / ".aggps-version").exists() and (td / ".aggps-smoke-ok").exists()
        # caller cwd must not have received markers
        assert not (Path.cwd() / ".aggps-version").exists()
        assert not (Path.cwd() / ".aggps-smoke-ok").exists()

    # ZIP checks (only the artifact(s) present for this platform)
    zips = list((root / "dist").glob("aggps-studio-*-windows-x64.zip")) + list((root / "dist").glob("aggps-studio-*-linux-x64.zip"))
    if len(zips) != 1:
        raise AssertionError(f"expected exactly 1 desktop zip in dist/, found {zips}")
    zp = zips[0]
    with zipfile.ZipFile(zp) as z:
        nl = [n for n in z.namelist() if n.strip()]
        tops = {n.split("/")[0] for n in nl}
        if len(tops) != 1 or "AgGPS Studio" not in tops:
            raise AssertionError(f"ZIP must have exactly one top-level 'AgGPS Studio' folder, got {tops}")
        if not any("templates/index.html" in n for n in nl):
            raise AssertionError("templates/index.html missing from ZIP")
        if not (any("static/app.js" in n for n in nl) or any("static/app.css" in n for n in nl)):
            raise AssertionError("static/ resources missing from ZIP")
        readme_member = "AgGPS Studio/BUNDLE_README.txt"
        if readme_member not in nl:
            raise AssertionError("BUNDLE_README.txt missing from ZIP")
        if THIRD_PARTY_NOTICES_FILENAME not in z.read(readme_member).decode("utf-8"):
            raise AssertionError(
                "BUNDLE_README.txt does not reference third-party notices"
            )
        if "AgGPS Studio/LICENSE.txt" not in nl:
            raise AssertionError("LICENSE.txt missing from ZIP")
        notices_member = f"AgGPS Studio/{THIRD_PARTY_NOTICES_FILENAME}"
        if notices_member not in nl:
            raise AssertionError("THIRD_PARTY_NOTICES.txt missing from ZIP")
        if z.getinfo(notices_member).file_size < 1_000:
            raise AssertionError("THIRD_PARTY_NOTICES.txt is unexpectedly small")
        if "windows" in zp.name:
            if not any(n.endswith("AgGPS Studio.exe") for n in nl):
                raise AssertionError("windows exe missing from ZIP")
        else:
            if not any("AgGPS Studio/AgGPS Studio" in n for n in nl):
                raise AssertionError("linux executable missing from ZIP")
        forbidden = ["jobs/", "_jobs/", "input.zip", ".git/", "tests/", "AgGPS.zip", "customer"]
        bad = [n for n in nl if any(f in n for f in forbidden)]
        if bad:
            raise AssertionError(f"forbidden content in ZIP: {bad[:3]}")

    # also assert the onedir bundle dir has the resources (for the copied final layout)
    if not ( (bundle_dir / "templates" / "index.html").exists() or (bundle_dir / "_internal" / "templates" / "index.html").exists() ):
        raise AssertionError("templates missing from final onedir bundle")
    if not ( (bundle_dir / "static" / "app.js").exists() or (bundle_dir / "_internal" / "static" / "app.js").exists() ):
        raise AssertionError("static missing from final onedir bundle")
    if not (bundle_dir / "LICENSE.txt").exists():
        raise AssertionError("LICENSE.txt missing from final onedir bundle")
    bundle_readme = bundle_dir / "BUNDLE_README.txt"
    if not bundle_readme.exists():
        raise AssertionError("BUNDLE_README.txt missing from final onedir bundle")
    if THIRD_PARTY_NOTICES_FILENAME not in bundle_readme.read_text(encoding="utf-8"):
        raise AssertionError(
            "BUNDLE_README.txt does not reference third-party notices"
        )
    if not (bundle_dir / THIRD_PARTY_NOTICES_FILENAME).exists():
        raise AssertionError(
            "THIRD_PARTY_NOTICES.txt missing from final onedir bundle"
        )
    _validate_third_party_notices(bundle_dir / THIRD_PARTY_NOTICES_FILENAME)

    print("verify: OK (exact markers, exit codes, ZIP layout, bundle contents)")


if __name__ == "__main__":
    main()
