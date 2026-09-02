from __future__ import annotations

import io
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app import JobManager, Settings, create_app


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


def _zip_bytes(payload: bytes = b"test") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("AgGPS/readme.txt", payload)
    return output.getvalue()


def _fake_processor(zip_path: Path, out_dir: Path, **options) -> dict:
    assert zip_path.is_file()
    maps = out_dir / "mapas"
    maps.mkdir(parents=True)
    (out_dir / "_extract").mkdir()
    (out_dir / "USB_Pro700").mkdir()
    aggps_zip = out_dir / "Farm_AgGPS.zip"
    shapefile_zip = out_dir / "Farm_Shapefile.zip"
    pdf = out_dir / "Farm_Mapas_choferes.pdf"
    images_zip = out_dir / "Farm_Mapas_lotes.zip"
    bundle = out_dir / "Farm_paquete_completo.zip"
    aggps_zip.write_bytes(b"aggps")
    shapefile_zip.write_bytes(b"shapefile")
    pdf.write_bytes(b"pdf")
    images_zip.write_bytes(b"images")
    bundle.write_bytes(b"bundle")
    (maps / "Field1_preview.jpg").write_bytes(b"jpg")
    (maps / "overview.jpg").write_bytes(b"overview")
    return {
        "title": "Grower <script> — Farm",
        "language": options.get("language", "es"),
        "n_fields": 1,
        "aggps_zip": str(aggps_zip),
        "shapefile_zip": str(shapefile_zip),
        "pdf": str(pdf),
        "images_zip": str(images_zip),
        "bundle": str(bundle),
        "fields": [
            {
                "client": "Grower <script>",
                "farm": "Farm & Sons",
                "field": "Field 1",
                "slug": "Field1",
                "note": "listo",
                "n_taipas": 3,
                "area_ha": 2.5,
            }
        ],
    }


def _login(client: TestClient) -> None:
    response = client.post("/auth/login", data={"password": PASSWORD})
    assert response.status_code == 200


def _wait_for_job(client: TestClient, poll_url: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(poll_url)
        assert response.status_code == 200
        state = response.json()
        if state["status"] in {"succeeded", "failed"}:
            return state
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_auth_health_and_security_headers(tmp_path: Path):
    application = create_app(_settings(tmp_path), processor=_fake_processor)
    with TestClient(application) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["ok"] is True

        root = client.get("/")
        assert root.status_code == 200
        assert '<option value="es" selected>' in root.text
        assert '<option value="pt-BR">' in root.text
        assert "script-src 'self'" in root.headers["content-security-policy"]
        assert root.headers["x-content-type-options"] == "nosniff"

        unauthorized = client.post(
            "/jobs",
            files={"zip": ("AgGPS.zip", _zip_bytes(), "application/zip")},
        )
        assert unauthorized.status_code == 401

        oversized_login = client.post("/auth/login", data={"password": "x" * 20_000})
        assert oversized_login.status_code == 413

        wrong = client.post("/auth/login", data={"password": "wrong-password"})
        assert wrong.status_code == 401
        login = client.post("/auth/login", data={"password": PASSWORD})
        assert login.status_code == 200
        cookie = login.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert client.get("/auth/session").json() == {"authenticated": True}

        logout = client.post("/auth/logout")
        assert logout.status_code == 200
        assert client.get("/auth/session").json() == {"authenticated": False}


def test_background_job_poll_and_protected_downloads(tmp_path: Path):
    processor_options = {}

    def recording_processor(zip_path: Path, out_dir: Path, **options) -> dict:
        processor_options.update(options)
        return _fake_processor(zip_path, out_dir, **options)

    application = create_app(_settings(tmp_path), processor=recording_processor)
    with TestClient(application) as client:
        _login(client)
        created = client.post(
            "/jobs",
            files={"zip": ("AgGPS.zip", _zip_bytes(), "application/zip")},
            data={"satellite": "false"},
        )
        assert created.status_code == 202
        state = _wait_for_job(client, created.json()["poll_url"])
        assert state["status"] == "succeeded"
        assert processor_options["fetch_sat"] is False
        assert processor_options["language"] == "es"
        assert state["result"]["language"] == "es"
        assert state["result"]["fields"][0]["client"] == "Grower <script>"
        assert state["result"]["artifact_files"]["aggps"] == "Farm_AgGPS.zip"
        assert "preview_url" in state["result"]["fields"][0]
        job_dir = tmp_path / "jobs" / state["job_id"]
        assert not (job_dir / "input.zip").exists()
        assert not (job_dir / "out" / "_extract").exists()
        assert not (job_dir / "out" / "USB_Pro700").exists()
        assert not (job_dir / "out" / "mapas" / "overview.jpg").exists()

        aggps = client.get(state["result"]["artifact_urls"]["aggps"])
        assert aggps.status_code == 200
        assert aggps.content == b"aggps"
        assert 'filename="Farm_AgGPS.zip"' in aggps.headers["content-disposition"]
        shapefile = client.get(state["result"]["artifact_urls"]["shapefile"])
        assert shapefile.status_code == 200
        assert shapefile.content == b"shapefile"
        images = client.get(state["result"]["artifact_urls"]["images"])
        assert images.status_code == 200
        assert images.content == b"images"
        preview = client.get(state["result"]["fields"][0]["preview_url"])
        assert preview.status_code == 200
        assert preview.content == b"jpg"

        preview_path = job_dir / "out" / "mapas" / "Field1_preview.jpg"
        preview_path.unlink()
        preview_path.with_suffix(".png").write_bytes(b"legacy-png")
        legacy_preview = client.get(state["result"]["fields"][0]["preview_url"])
        assert legacy_preview.status_code == 200
        assert legacy_preview.headers["content-type"].startswith("image/png")
        assert legacy_preview.content == b"legacy-png"

        client.cookies.clear()
        assert client.get(state["result"]["artifact_urls"]["aggps"]).status_code == 401

    javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in javascript
    assert "textContent" in javascript
    assert "body.append('language'" in javascript


def test_job_accepts_brazilian_portuguese_and_rejects_unknown_language(tmp_path: Path):
    processor_options = {}

    def recording_processor(zip_path: Path, out_dir: Path, **options) -> dict:
        processor_options.update(options)
        return _fake_processor(zip_path, out_dir, **options)

    application = create_app(_settings(tmp_path), processor=recording_processor)
    with TestClient(application) as client:
        _login(client)
        rejected = client.post(
            "/jobs",
            files={"zip": ("AgGPS.zip", _zip_bytes(), "application/zip")},
            data={"language": "pt"},
        )
        assert rejected.status_code == 400

        created = client.post(
            "/jobs",
            files={"zip": ("AgGPS.zip", _zip_bytes(), "application/zip")},
            data={"language": "pt-BR"},
        )
        assert created.status_code == 202
        state = _wait_for_job(client, created.json()["poll_url"])
        assert state["status"] == "succeeded"
        assert processor_options["language"] == "pt-BR"
        assert state["result"]["language"] == "pt-BR"


def test_upload_limit_and_invalid_zip_leave_no_jobs(tmp_path: Path):
    settings = _settings(tmp_path, max_upload_bytes=128)
    application = create_app(settings, processor=_fake_processor)
    with TestClient(application) as client:
        _login(client)
        oversized = client.post(
            "/jobs",
            files={"zip": ("large.zip", _zip_bytes(b"x" * 2048), "application/zip")},
        )
        assert oversized.status_code == 413
        invalid = client.post(
            "/jobs",
            files={"zip": ("bad.zip", b"not a zip", "application/zip")},
        )
        assert invalid.status_code == 400
    assert not any(settings.jobs_dir.iterdir())


def test_executor_bounds_concurrent_processing(tmp_path: Path):
    lock = threading.Lock()
    active = 0
    maximum = 0

    def slow_processor(zip_path: Path, out_dir: Path, **kwargs) -> dict:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(0.1)
            return _fake_processor(zip_path, out_dir, **kwargs)
        finally:
            with lock:
                active -= 1

    application = create_app(_settings(tmp_path, max_concurrent_jobs=1), processor=slow_processor)
    with TestClient(application) as client:
        _login(client)
        first = client.post(
            "/jobs",
            files={"zip": ("one.zip", _zip_bytes(b"one"), "application/zip")},
        ).json()
        second = client.post(
            "/jobs",
            files={"zip": ("two.zip", _zip_bytes(b"two"), "application/zip")},
        ).json()
        assert _wait_for_job(client, first["poll_url"])["status"] == "succeeded"
        assert _wait_for_job(client, second["poll_url"])["status"] == "succeeded"
    assert maximum == 1


def test_ttl_cleanup_removes_terminal_job(tmp_path: Path):
    settings = _settings(tmp_path)
    manager = JobManager(settings, _fake_processor)
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    manager.write_state(
        "a" * 16,
        {
            "job_id": "a" * 16,
            "status": "succeeded",
            "expires_at": expired.isoformat(),
        },
    )
    manager.cleanup_expired()
    assert not (settings.jobs_dir / ("a" * 16)).exists()


def test_expired_job_blocks_direct_artifact_download(tmp_path: Path):
    settings = _settings(tmp_path)
    application = create_app(settings, processor=_fake_processor)
    job_id = "b" * 16
    job_dir = settings.jobs_dir / job_id
    with TestClient(application) as client:
        _login(client)
        artifact = job_dir / "out" / "Farm_AgGPS.zip"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"expired")
        application.state.job_manager.write_state(
            job_id,
            {
                "job_id": job_id,
                "status": "succeeded",
                "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                "result": {
                    "fields": [],
                    "artifact_files": {"aggps": "Farm_AgGPS.zip"},
                },
            },
        )
        response = client.get(f"/jobs/{job_id}/artifacts/aggps")
        assert response.status_code == 410
    assert not job_dir.exists()


def test_retained_legacy_job_artifacts_remain_downloadable(tmp_path: Path):
    settings = _settings(tmp_path)
    application = create_app(settings, processor=_fake_processor)
    job_id = "c" * 16
    job_dir = settings.jobs_dir / job_id
    artifacts = {
        "USB_Pro700.zip": b"legacy-usb",
        "Mapas_choferes.pdf": b"legacy-pdf",
        "paquete_completo.zip": b"legacy-bundle",
    }
    with TestClient(application) as client:
        _login(client)
        out_dir = job_dir / "out"
        out_dir.mkdir(parents=True)
        for filename, content in artifacts.items():
            (out_dir / filename).write_bytes(content)
        application.state.job_manager.write_state(
            job_id,
            {
                "job_id": job_id,
                "status": "succeeded",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "result": {
                    "title": "Legacy farm",
                    "n_fields": 0,
                    "fields": [],
                    "artifact_urls": {
                        "usb": f"/jobs/{job_id}/artifacts/usb",
                        "pdf": f"/jobs/{job_id}/artifacts/pdf",
                        "bundle": f"/jobs/{job_id}/artifacts/bundle",
                    },
                },
            },
        )
        state = client.get(f"/jobs/{job_id}")
        assert state.status_code == 200
        assert state.json()["result"]["artifact_urls"]["usb"].endswith("/artifacts/usb")
        assert client.get(f"/jobs/{job_id}/artifacts/usb").content == b"legacy-usb"
        assert client.get(f"/jobs/{job_id}/artifacts/pdf").content == b"legacy-pdf"
        assert client.get(f"/jobs/{job_id}/artifacts/bundle").content == b"legacy-bundle"

    javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    assert "data.artifact_urls.aggps || data.artifact_urls.usb" in javascript


def test_login_failures_are_throttled(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.LOGIN_FAILURE_LIMIT", 1)
    application = create_app(_settings(tmp_path), processor=_fake_processor)
    with TestClient(application) as client:
        assert client.post("/auth/login", data={"password": "wrong"}).status_code == 401
        blocked = client.post("/auth/login", data={"password": "still-wrong"})
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "60"
