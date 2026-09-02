#!/usr/bin/env python3
"""Thin desktop entrypoint using pywebview + embedded FastAPI server.

- Loopback-only ephemeral port via pre-bound socket.
- Uses uvicorn.Server.run(sockets=[sock]) (Windows-safe, no fd= config assumption).
- Socket remains open/owned until after server shutdown.
- platformdirs + MPLCONFIGDIR established before any app/engine import.
- Explicit desktop_mode for auth bypass (no login).
- Native pywebview downloads via ALLOW_DOWNLOADS (no custom bridge).
- --smoke-test: server only, healthz + /auth/session, clean exit, "desktop-smoke: OK".
- --gui-smoke-test: real GUI backend probe (imports pywebview + GTK/Edge platform), minimal window+server, auto close, "desktop-gui-smoke: OK" only on native init success.
- --version: frozen-safe via lightweight version module (no source parsing).
- Errors on import/start: concise stderr + Linux guidance, nonzero, no traceback for expected runtime-missing cases.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import platformdirs

from version import APP_VERSION


_SENSITIVE_EXCEPTION_VALUE_RE = re.compile(
    r"(?i)\b(password|passphrase|secret|token|api[_-]?key|authorization)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


def _write_ci_marker(name: str, content: str) -> None:
    """Write a sidecar marker file ONLY when AGGPS_DESKTOP_VERIFY_DIR is set.
    Used exclusively by frozen-bundle verification (which points the env at a
    temp directory) so that normal users and ordinary runs never create .aggps-*
    litter in the current working directory. Windowed frozen builds may suppress
    stdout, hence the marker sidecar for verification only.
    """
    verify_dir = os.environ.get("AGGPS_DESKTOP_VERIFY_DIR")
    if not verify_dir:
        return
    try:
        (Path(verify_dir) / name).write_text(content + "\n", encoding="utf-8")
    except Exception:
        pass


def _concise_exception_summary(exc: Exception) -> str:
    """Return a single-line diagnostic without common credential values."""
    try:
        message = " ".join(str(exc).split()) or "<no message>"
    except Exception:
        message = "<unprintable message>"
    message = _SENSITIVE_EXCEPTION_VALUE_RE.sub(r"\1\2<redacted>", message)
    message = re.sub(r"(?i)\bbearer\s+\S+", "Bearer <redacted>", message)
    if len(message) > 500:
        message = message[:497] + "..."
    return f"{type(exc).__name__}: {message}"


def _ensure_mpl_and_dirs() -> tuple[Path, Path]:
    """Set MPLCONFIGDIR and ensure user-writable jobs/cache before any matplotlib/app imports."""
    cache_root = Path(platformdirs.user_cache_dir("aggps-studio"))
    jobs_root = Path(platformdirs.user_data_dir("aggps-studio"))
    mpl_dir = cache_root / "mpl"
    mpl_dir.mkdir(parents=True, exist_ok=True)
    jobs_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_dir))
    return jobs_root, cache_root


def _desktop_settings(jobs_dir: Path) -> "Settings":
    """Ephemeral secrets to satisfy Settings validation; desktop_mode bypasses auth."""
    from app import Settings

    return Settings(
        jobs_dir=jobs_dir,
        password=secrets.token_urlsafe(24),
        session_secret=secrets.token_hex(32),
    )


def _wait_for(url: str, timeout: float = 8.0) -> None:
    """Poll until URL responds with <500 status. Small sleeps to avoid flakiness."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.8) as resp:
                if resp.status < 500:
                    return
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_err = e
        time.sleep(0.03)
    raise RuntimeError(f"server not ready: {url}") from last_err


class DesktopServer:
    """Small reusable context manager for the desktop FastAPI server.

    Binds 127.0.0.1:0 (ephemeral), ensures listening, runs uvicorn via
    Server.run(sockets=[sock]) so the pre-bound socket is used directly.
    The socket is closed only after the server thread has been signalled
    and joined. Cross-platform (Windows + Linux).
    """

    def __init__(self, asgi_app: Any, *, log_level: str = "warning") -> None:
        self.asgi_app = asgi_app
        self.log_level = log_level
        self._sock: socket.socket | None = None
        self._port: int | None = None
        self._server: Any | None = None  # uvicorn.Server
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("DesktopServer not entered")
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> DesktopServer:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # SO_REUSEPORT not used: not portable to Windows
        self._sock.bind(("127.0.0.1", 0))
        # Ensure the socket is listening and owned before handing to uvicorn
        self._sock.listen(128)
        self._port = self._sock.getsockname()[1]

        import uvicorn

        config = uvicorn.Config(
            app=self.asgi_app,
            host="127.0.0.1",
            port=self._port,
            log_level=self.log_level,
            access_log=False,
            # deliberately no fd=; we pass the socket object via run(sockets=)
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run,
            kwargs={"sockets": [self._sock]},
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = self._server = self._thread = None


def _handle_missing_webview(exc: Exception) -> None:
    if sys.platform.startswith("linux"):
        hint = (
            "Install Linux webview deps, e.g.:\n"
            "  sudo apt-get install -y gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 gir1.2-gtk-3.0\n"
            "Then: pip install -r requirements-desktop.txt"
        )
    else:
        hint = (
            "On Windows, Edge WebView2 Evergreen is present on most systems.\n"
            "If missing, install the Evergreen bootstrapper from the official Microsoft page:\n"
            "  https://developer.microsoft.com/en-us/microsoft-edge/webview2/\n"
            "(This package does not bundle the runtime.)"
        )
    # concise, no traceback for expected
    raise RuntimeError(f"pywebview unavailable: {exc}\n{hint}") from None


def _run_smoke_test() -> None:
    """Start desktop-mode server on ephemeral prebound port, verify healthz + authenticated session, clean shutdown. No GUI."""
    _ensure_mpl_and_dirs()

    import uvicorn  # ensure available for smoke (base req)

    from app import Settings, create_app

    with tempfile.TemporaryDirectory(prefix="aggps-desktop-smoke-") as td:
        tmp_jobs = Path(td) / "jobs"
        tmp_jobs.mkdir()
        # Use realistic settings; desktop_mode skips password length gate
        settings = Settings(
            jobs_dir=tmp_jobs,
            password=secrets.token_urlsafe(24),
            session_secret=secrets.token_hex(32),
        )
        app = create_app(settings=settings, desktop_mode=True)

        with DesktopServer(app, log_level="critical") as srv:
            _wait_for(srv.base_url + "/healthz")
            sess = json.loads(urllib.request.urlopen(srv.base_url + "/auth/session", timeout=1).read())
            if not sess.get("authenticated"):
                raise AssertionError("/auth/session must report authenticated in desktop_mode")

    print("desktop-smoke: OK")
    _write_ci_marker(".aggps-smoke-ok", "OK")


def _run_gui_smoke_test() -> None:
    """Packaged GUI backend probe: imports pywebview (triggers platform/gi on Linux), starts embedded server + minimal real window,
    and auto-closes from pywebview's post-start callback. Exits 0 only if the native backend (GTK/Edge) initializes successfully.
    Ordinary --smoke-test is server-only and never imports webview.
    """
    _ensure_mpl_and_dirs()

    try:
        import webview
    except Exception as exc:
        _handle_missing_webview(exc)

    from app import Settings, create_app

    # Use temp jobs (same pattern as smoke); desktop_mode for no-auth
    with tempfile.TemporaryDirectory(prefix="aggps-gui-smoke-") as td:
        tmp_jobs = Path(td) / "jobs"
        tmp_jobs.mkdir()
        settings = Settings(
            jobs_dir=tmp_jobs,
            password=secrets.token_urlsafe(24),
            session_secret=secrets.token_hex(32),
        )
        app = create_app(settings=settings, desktop_mode=True)

        with DesktopServer(app, log_level="critical") as srv:
            _wait_for(srv.base_url + "/healthz")

            webview.settings["ALLOW_DOWNLOADS"] = True

            win = webview.create_window(
                "AgGPS Studio GUI-Smoke",
                srv.base_url + "/",
                width=480,
                height=320,
                resizable=False,
            )

            def _close_after_start() -> None:
                time.sleep(0.7)
                win.destroy()

            # start blocks until destroy() or external quit
            try:
                webview.start(_close_after_start)
            except Exception as exc:
                _handle_missing_webview(exc)

    # if we reached here without raising _handle, native backend initialized successfully
    print("desktop-gui-smoke: OK")
    _write_ci_marker(".aggps-gui-smoke-ok", "OK")


def _run_gui_smoke_test_with_diagnostics() -> int:
    """Run the GUI smoke probe and persist a frozen-build failure diagnostic."""
    try:
        _run_gui_smoke_test()
    except Exception as exc:
        summary = _concise_exception_summary(exc)
        _write_ci_marker(".aggps-gui-smoke-error", summary)
        print(f"desktop-gui-smoke: ERROR: {summary}", file=sys.stderr)
        return 1
    return 0


def _run_desktop() -> None:
    jobs_dir, _ = _ensure_mpl_and_dirs()

    try:
        import webview
    except Exception as exc:
        _handle_missing_webview(exc)

    from app import create_app

    settings = _desktop_settings(jobs_dir)
    app = create_app(settings=settings, desktop_mode=True)

    try:
        with DesktopServer(app, log_level="warning") as srv:
            _wait_for(srv.base_url + "/healthz")

            # Enable pywebview's maintained native download support explicitly.
            # No custom JS/save bridge is used.
            webview.settings["ALLOW_DOWNLOADS"] = True

            webview.create_window(
                f"AgGPS Studio v{APP_VERSION}",
                srv.base_url + "/",
                width=1080,
                height=720,
                resizable=True,
            )
            webview.start()
    except Exception as exc:
        # webview.start() can raise for missing native runtime (e.g. GTK/WebKit)
        _handle_missing_webview(exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="AgGPS Studio (desktop)")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument("--smoke-test", action="store_true", help="verify server+desktop auth, no GUI")
    parser.add_argument("--gui-smoke-test", action="store_true", help="verify real packaged GUI backend (GTK/Edge) init: imports pywebview, starts minimal window+server, auto-closes after load/timeout; exits 0 only on success. Ordinary --smoke-test remains server-only.")
    args = parser.parse_args()

    if args.version:
        # Lightweight import: version.py has no side effects or heavy deps (matplotlib/engine).
        # Works in frozen PyInstaller bundles (just the .py + dist metadata if present).
        from version import APP_VERSION

        print(APP_VERSION)
        _write_ci_marker(".aggps-version", APP_VERSION)
        return

    if args.smoke_test:
        _run_smoke_test()
        return

    if args.gui_smoke_test:
        exit_code = _run_gui_smoke_test_with_diagnostics()
        if exit_code:
            sys.exit(exit_code)
        return

    try:
        _run_desktop()
    except RuntimeError as exc:
        # Expected missing-runtime cases: concise on stderr, nonzero, no traceback.
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # Unexpected: let Python print traceback + nonzero.
        print(f"unexpected desktop error: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
