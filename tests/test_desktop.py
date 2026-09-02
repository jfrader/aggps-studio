from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import Settings, create_app

# Desktop tests are focused here (not appended to test_web.py).
# They exercise auth isolation (always) and server lifecycle via the reusable
# DesktopServer when uvicorn is available. No webview required for these tests.
# Avoids low-level duplicate lifecycle code and arbitrary sleeps.

PASSWORD = "tractor-test-password"


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "jobs_dir": tmp_path / "jobs",
        "password": PASSWORD,
        "session_secret": "test-session-secret-with-enough-entropy",
        "max_upload_bytes": 1024 * 1024,
        "max_extracted_bytes": 5 * 1024 * 1024,
        "max_zip_member_bytes": 1024 * 1024,
        "max_zip_members": 50,
        "max_concurrent_jobs": 1,
        "max_pending_jobs": 5,
        "job_ttl_seconds": 3600,
        "cleanup_interval_seconds": 3600,
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings(**values)


def _fake_processor(zip_path: Path, out_dir: Path, **options) -> dict:
    # minimal to satisfy create_job etc if used
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "Farm_AgGPS.zip").write_bytes(b"aggps")
    return {
        "title": "Test",
        "language": "es",
        "n_fields": 0,
        "fields": [],
        "aggps_zip": str(out_dir / "Farm_AgGPS.zip"),
        "shapefile_zip": "",
        "pdf": "",
        "images_zip": "",
        "bundle": "",
    }


def test_desktop_mode_auth_isolation(tmp_path: Path):
    """desktop_mode=True makes /auth/session always true and bypasses require_auth for *that* app instance only.
    Normal web/Docker instances (desktop_mode=False or default) remain authenticated.
    """
    settings = _settings(tmp_path)
    desktop_app = create_app(settings, processor=_fake_processor, desktop_mode=True)
    normal_app = create_app(settings, processor=_fake_processor, desktop_mode=False)

    with TestClient(desktop_app) as c:
        assert c.get("/auth/session").json() == {"authenticated": True, "desktop": True}
        # protected route: require_auth short-circuits, so we get 404 (no job) not 401
        r = c.get("/jobs/ffffffffffffffff")
        assert r.status_code in (404, 410)

    with TestClient(normal_app) as c:
        assert c.get("/auth/session").json() == {"authenticated": False}
        r = c.get("/jobs/ffffffffffffffff")
        assert r.status_code == 401


def _has_uvicorn() -> bool:
    try:
        import uvicorn  # noqa: F401
        return True
    except Exception:
        return False


def test_linux_desktop_forces_gtk_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    import desktop

    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.delenv("GDK_BACKEND", raising=False)

    assert desktop._native_webview_gui() == "gtk"
    assert desktop.os.environ["GDK_BACKEND"] == "x11"


@pytest.mark.skipif(not _has_uvicorn(), reason="uvicorn not available for server lifecycle test")
def test_desktop_server_lifecycle(tmp_path: Path):
    """Uses the reusable DesktopServer context manager.
    Verifies pre-bound ephemeral loopback, healthz, desktop auth session, clean shutdown.
    No GUI, no webview, no arbitrary fixed sleeps (polling wait inside).
    """
    from desktop import DesktopServer

    settings = _settings(tmp_path)
    app = create_app(settings, processor=_fake_processor, desktop_mode=True)

    with DesktopServer(app, log_level="critical") as srv:
        # poll health (internal wait avoids flakiness)
        deadline = time.monotonic() + 6.0
        last = None
        while time.monotonic() < deadline:
            try:
                resp = urllib.request.urlopen(srv.base_url + "/healthz", timeout=0.6)
                if resp.status == 200:
                    break
            except Exception as e:
                last = e
            time.sleep(0.02)
        else:
            pytest.fail(f"healthz not reachable: {last}")

        sess = json.loads(urllib.request.urlopen(srv.base_url + "/auth/session", timeout=0.6).read())
        assert sess.get("authenticated") is True

        # port is OS-assigned ephemeral
        assert srv.port > 0
        assert "127.0.0.1" in srv.base_url

    # after context: server stopped and socket closed (no exception raised on exit)
    # (we do not assert port reuse here to avoid platform timing flakes)
