#!/usr/bin/env python3
"""Authenticated FastAPI UI for the AgGPS conversion engine."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import sys
import threading
import time
import uuid
import zipfile
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from engine.languages import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from engine.pipeline import UnsafeArchiveError, process_aggps_zip

from version import APP_VERSION


def _get_base_dir() -> Path:
    """Base directory for templates/static. Supports frozen bundles (e.g. PyInstaller _MEIPASS)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


ROOT = _get_base_dir()
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
STATIC_DIR = ROOT / "static"
SESSION_COOKIE = "aggps_session"
JOB_ID_RE = re.compile(r"^[a-f0-9]{16}$")
ARTIFACTS = {
    "aggps": ("aggps_zip", "application/zip"),
    "shapefile": ("shapefile_zip", "application/zip"),
    "pdf": ("pdf", "application/pdf"),
    "images": ("images_zip", "application/zip"),
    "bundle": ("bundle", "application/zip"),
}
LEGACY_ARTIFACTS = {
    "usb": ("USB_Pro700.zip", "application/zip"),
    "pdf": ("Mapas_choferes.pdf", "application/pdf"),
    "bundle": ("paquete_completo.zip", "application/zip"),
}
LOGIN_FAILURE_LIMIT = 8
LOGIN_FAILURE_WINDOW_SECONDS = 60
logger = logging.getLogger("aggps_studio")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    jobs_dir: Path
    password: str
    session_secret: str
    host: str = "127.0.0.1"
    port: int = 8765
    max_upload_bytes: int = 50 * 1024 * 1024
    max_extracted_bytes: int = 300 * 1024 * 1024
    max_zip_member_bytes: int = 100 * 1024 * 1024
    max_zip_members: int = 1000
    max_concurrent_jobs: int = 1
    max_pending_jobs: int = 20
    job_ttl_seconds: int = 24 * 60 * 60
    cleanup_interval_seconds: int = 15 * 60
    session_max_age_seconds: int = 12 * 60 * 60
    cookie_secure: bool = False

    @property
    def max_request_bytes(self) -> int:
        return self.max_upload_bytes + 2 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        password = os.environ.get("AGGPS_STUDIO_PASSWORD", "")
        return cls(
            jobs_dir=Path(os.environ.get("JOBS_DIR", ROOT / "_jobs")),
            password=password,
            session_secret=os.environ.get("AGGPS_SESSION_SECRET") or password,
            host=os.environ.get("HOST", "127.0.0.1"),
            port=_env_int("PORT", 8765),
            max_upload_bytes=_env_int("MAX_UPLOAD_MB", 50) * 1024 * 1024,
            max_extracted_bytes=_env_int("MAX_EXTRACTED_MB", 300) * 1024 * 1024,
            max_zip_member_bytes=_env_int("MAX_ZIP_MEMBER_MB", 100) * 1024 * 1024,
            max_zip_members=_env_int("MAX_ZIP_MEMBERS", 1000),
            max_concurrent_jobs=_env_int("MAX_CONCURRENT_JOBS", 1),
            max_pending_jobs=_env_int("MAX_PENDING_JOBS", 20),
            job_ttl_seconds=_env_int("JOB_TTL_HOURS", 24) * 60 * 60,
            cleanup_interval_seconds=_env_int("JOB_CLEANUP_INTERVAL_SECONDS", 900, 10),
            session_max_age_seconds=_env_int("SESSION_HOURS", 12) * 60 * 60,
            cookie_secure=_env_bool("COOKIE_SECURE"),
        )


class PayloadTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Count request bytes before Starlette's form parser can spool them."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        limits = {
            "/auth/login": (16 * 1024, "La solicitud de acceso supera el límite permitido."),
            "/auth/logout": (1024, "La solicitud supera el límite permitido."),
            "/jobs": (self.max_bytes, "El archivo supera el límite de carga."),
        }
        limit_config = limits.get(scope["path"])
        if not limit_config:
            await self.app(scope, receive, send)
            return
        limit, rejection_detail = limit_config

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > limit:
                    await self._reject(scope, receive, send, rejection_detail)
                    return
            except ValueError:
                await self._reject(scope, receive, send, rejection_detail)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise PayloadTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except PayloadTooLarge:
            await self._reject(scope, receive, send, rejection_detail)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, detail: str) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": detail},
        )
        await response(scope, receive, send)


class SessionAuth:
    def __init__(self, secret: str, max_age_seconds: int) -> None:
        self.serializer = URLSafeTimedSerializer(secret, salt="aggps-studio-session")
        self.max_age_seconds = max_age_seconds

    def issue(self) -> str:
        return self.serializer.dumps({"authenticated": True, "version": 1})

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            payload = self.serializer.loads(token, max_age=self.max_age_seconds)
        except (BadSignature, SignatureExpired):
            return False
        return payload == {"authenticated": True, "version": 1}


Processor = Callable[..., dict]


class JobManager:
    def __init__(self, settings: Settings, processor: Processor) -> None:
        self.settings = settings
        self.processor = processor
        self._executor: ThreadPoolExecutor | None = None
        self._active: set[str] = set()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._cleanup_thread: threading.Thread | None = None

    def start(self) -> None:
        self.settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        probe = self.settings.jobs_dir / ".write-test"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        self._executor = ThreadPoolExecutor(
            max_workers=self.settings.max_concurrent_jobs,
            thread_name_prefix="aggps-job",
        )
        self.cleanup_expired()
        for job_dir in self.settings.jobs_dir.iterdir():
            if not job_dir.is_dir() or not JOB_ID_RE.fullmatch(job_dir.name):
                continue
            state = self.read_state(job_dir.name)
            status = state.get("status") if state else None
            if status in {"succeeded", "failed"}:
                self._discard_working_data(job_dir, succeeded=status == "succeeded")
            elif status in {"queued", "processing"}:
                if (job_dir / "input.zip").is_file():
                    state["status"] = "queued"
                    state["updated_at"] = _now_iso()
                    self.write_state(job_dir.name, state)
                    self.submit(job_dir.name)
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="aggps-cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=2)
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=False)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._active)

    def job_dir(self, job_id: str) -> Path | None:
        if not JOB_ID_RE.fullmatch(job_id):
            return None
        return self.settings.jobs_dir / job_id

    def read_state(self, job_id: str) -> dict | None:
        job_dir = self.job_dir(job_id)
        if not job_dir:
            return None
        try:
            return json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def write_state(self, job_id: str, state: dict) -> None:
        job_dir = self.job_dir(job_id)
        if not job_dir:
            raise ValueError("invalid job id")
        job_dir.mkdir(parents=True, exist_ok=True)
        tmp = job_dir / f"state-{uuid.uuid4().hex}.tmp"
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, job_dir / "state.json")

    def submit(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._active:
                return
            if not self._executor:
                raise RuntimeError("job manager is not running")
            self._active.add(job_id)
            try:
                self._executor.submit(self._run, job_id)
            except Exception:
                self._active.discard(job_id)
                raise

    def _run(self, job_id: str) -> None:
        state = self.read_state(job_id)
        job_dir = self.job_dir(job_id)
        if not state or not job_dir:
            with self._lock:
                self._active.discard(job_id)
            return
        succeeded = False
        try:
            state.update(status="processing", updated_at=_now_iso(), error=None)
            self.write_state(job_id, state)
            out_dir = job_dir / "out"
            if out_dir.exists():
                shutil.rmtree(out_dir)
            result = self.processor(
                job_dir / "input.zip",
                out_dir,
                fetch_sat=state.get("satellite", True) is True,
                language=str(state.get("language") or DEFAULT_LANGUAGE),
                max_members=self.settings.max_zip_members,
                max_per_member=self.settings.max_zip_member_bytes,
                max_total_uncompressed=self.settings.max_extracted_bytes,
            )
            now = datetime.now(timezone.utc)
            state.update(
                status="succeeded",
                updated_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=self.settings.job_ttl_seconds)).isoformat(),
                result=self._public_result(job_id, result, out_dir),
                error=None,
            )
            self._discard_working_data(job_dir, succeeded=True)
            self.write_state(job_id, state)
            succeeded = True
        except Exception as exc:
            logger.exception("job %s failed", job_id)
            now = datetime.now(timezone.utc)
            state.update(
                status="failed",
                updated_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=self.settings.job_ttl_seconds)).isoformat(),
                result=None,
                error=_public_error(exc),
            )
            self._discard_working_data(job_dir, succeeded=False)
            self.write_state(job_id, state)
        finally:
            self._discard_working_data(job_dir, succeeded=succeeded)
            with self._lock:
                self._active.discard(job_id)

    @staticmethod
    def _discard_working_data(job_dir: Path, *, succeeded: bool) -> None:
        try:
            (job_dir / "input.zip").unlink(missing_ok=True)
        except OSError:
            logger.warning("could not delete uploaded zip for job %s", job_dir.name)
        out_dir = job_dir / "out"
        if succeeded:
            shutil.rmtree(out_dir / "_extract", ignore_errors=True)
            shutil.rmtree(out_dir / "USB_Pro700", ignore_errors=True)
            maps_dir = out_dir / "mapas"
            for temporary_map in [maps_dir / "overview.jpg"]:
                try:
                    temporary_map.unlink(missing_ok=True)
                except OSError:
                    logger.warning("could not delete working map for job %s", job_dir.name)
        else:
            shutil.rmtree(out_dir, ignore_errors=True)

    @staticmethod
    def _public_result(job_id: str, result: dict, out_dir: Path) -> dict:
        fields = []
        for field in result.get("fields", []):
            slug = str(field.get("slug", ""))
            preview = out_dir / "mapas" / f"{slug}_preview.jpg"
            fields.append(
                {
                    "client": str(field.get("client", "")),
                    "farm": str(field.get("farm", "")),
                    "field": str(field.get("field", "")),
                    "slug": slug,
                    "note": str(field.get("note") or ""),
                    "n_taipas": field.get("n_taipas"),
                    "area_ha": field.get("area_ha"),
                    "preview_url": f"/jobs/{job_id}/previews/{slug}" if preview.is_file() else None,
                }
            )
        artifact_files = {}
        for kind, (result_key, _) in ARTIFACTS.items():
            filename = Path(str(result.get(result_key, ""))).name
            if filename and (out_dir / filename).is_file():
                artifact_files[kind] = filename
        return {
            "title": str(result.get("title", "Campos AgGPS")),
            "language": str(result.get("language") or DEFAULT_LANGUAGE),
            "n_fields": int(result.get("n_fields", len(fields))),
            "fields": fields,
            "artifact_files": artifact_files,
            "artifact_urls": {
                kind: f"/jobs/{job_id}/artifacts/{kind}" for kind in artifact_files
            },
        }

    def cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        if not self.settings.jobs_dir.exists():
            return
        for job_dir in self.settings.jobs_dir.iterdir():
            if not job_dir.is_dir() or not JOB_ID_RE.fullmatch(job_dir.name):
                continue
            state = self.read_state(job_dir.name)
            if state:
                expires_at = _parse_time(state.get("expires_at"))
                if state.get("status") in {"succeeded", "failed"} and expires_at and expires_at <= now:
                    shutil.rmtree(job_dir, ignore_errors=True)
            else:
                age = now.timestamp() - job_dir.stat().st_mtime
                if age > self.settings.job_ttl_seconds:
                    shutil.rmtree(job_dir, ignore_errors=True)

    def _cleanup_loop(self) -> None:
        while not self._stop.wait(self.settings.cleanup_interval_seconds):
            try:
                self.cleanup_expired()
            except Exception:
                logger.exception("job cleanup failed")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _public_error(exc: Exception) -> str:
    if isinstance(exc, UnsafeArchiveError):
        return "El zip contiene rutas o tamaños no permitidos."
    if isinstance(exc, zipfile.BadZipFile):
        return "El archivo no es un zip válido."
    if isinstance(exc, ValueError):
        message = str(exc)
        if message.startswith("No encontré carpetas AgGPS"):
            return message
        if "sidecar" in message or "must be exactly" in message:
            return "El zip contiene shapefiles incompletos o incompatibles con el Pro 700."
    return "No se pudo procesar el zip. Revisá el archivo e intentá de nuevo."


def require_auth(request: Request) -> None:
    if getattr(request.app.state, "desktop_mode", False):
        return
    auth: SessionAuth = request.app.state.auth
    if not auth.valid(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="Iniciá sesión para continuar.")


def create_app(
    settings: Settings | None = None,
    processor: Processor = process_aggps_zip,
    desktop_mode: bool = False,
) -> FastAPI:
    if settings is None:
        settings = Settings.from_env()
    auth = SessionAuth(settings.session_secret, settings.session_max_age_seconds)
    manager = JobManager(settings, processor)
    login_failures: dict[str, deque[float]] = defaultdict(deque)
    login_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if not desktop_mode and len(settings.password) < 12:
            raise RuntimeError("AGGPS_STUDIO_PASSWORD must contain at least 12 characters")
        manager.start()
        try:
            yield
        finally:
            manager.stop()

    application = FastAPI(
        title="AgGPS Studio",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.auth = auth
    application.state.job_manager = manager
    application.state.desktop_mode = desktop_mode
    application.add_middleware(RequestBodyLimitMiddleware, max_bytes=settings.max_request_bytes)
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'; object-src 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        else:
            response.headers["Cache-Control"] = "no-store"
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @application.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(INDEX_HTML)

    @application.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "version": APP_VERSION}

    @application.get("/auth/session")
    async def auth_session(request: Request) -> dict:
        if getattr(request.app.state, "desktop_mode", False):
            return {"authenticated": True, "desktop": True}
        return {"authenticated": auth.valid(request.cookies.get(SESSION_COOKIE))}

    @application.post("/auth/login")
    async def login(request: Request, password: str = Form(...)) -> JSONResponse:
        peer = request.client.host if request.client else "unknown"
        now = time.monotonic()
        async with login_lock:
            failures = login_failures[peer]
            while failures and now - failures[0] >= LOGIN_FAILURE_WINDOW_SECONDS:
                failures.popleft()
            if len(failures) >= LOGIN_FAILURE_LIMIT:
                raise HTTPException(
                    status_code=429,
                    detail="Demasiados intentos. Esperá un minuto.",
                    headers={"Retry-After": str(LOGIN_FAILURE_WINDOW_SECONDS)},
                )
            password_valid = secrets.compare_digest(password, settings.password)
            if password_valid:
                login_failures.pop(peer, None)
            else:
                failures.append(now)
        if not password_valid:
            await asyncio.sleep(0.5)
            raise HTTPException(status_code=401, detail="Contraseña incorrecta.")
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            SESSION_COOKIE,
            auth.issue(),
            max_age=settings.session_max_age_seconds,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            path="/",
        )
        return response

    @application.post("/auth/logout")
    async def logout() -> JSONResponse:
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
            secure=settings.cookie_secure,
            httponly=True,
            samesite="strict",
        )
        return response

    @application.post("/jobs", status_code=202, dependencies=[Depends(require_auth)])
    async def create_job(
        upload: UploadFile = File(..., alias="zip"),
        satellite: bool = Form(True),
        language: str = Form(DEFAULT_LANGUAGE),
    ) -> JSONResponse:
        if manager.pending_count >= settings.max_pending_jobs:
            raise HTTPException(status_code=429, detail="Hay demasiados trabajos pendientes.")
        filename = Path(upload.filename or "").name
        if not filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Subí un archivo .zip de AgGPS.")
        if language not in SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=400, detail="Elegí un idioma disponible.")

        job_id = uuid.uuid4().hex[:16]
        job_dir = settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, mode=0o700)
        temporary = job_dir / "input.tmp"
        total = 0
        try:
            with temporary.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    total += len(chunk)
                    if total > settings.max_upload_bytes:
                        raise HTTPException(status_code=413, detail="El zip supera el límite de carga.")
                    output.write(chunk)
            source = job_dir / "input.zip"
            os.replace(temporary, source)
            if not zipfile.is_zipfile(source):
                raise HTTPException(status_code=400, detail="El archivo no es un zip válido.")
            now = datetime.now(timezone.utc)
            safe_name = "".join(char for char in filename if char.isprintable())[:120]
            state = {
                "job_id": job_id,
                "status": "queued",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=settings.job_ttl_seconds)).isoformat(),
                "input_name": safe_name,
                "satellite": satellite,
                "language": language,
                "result": None,
                "error": None,
            }
            manager.write_state(job_id, state)
            manager.submit(job_id)
        except HTTPException:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        finally:
            await upload.close()

        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": "queued",
                "poll_url": f"/jobs/{job_id}",
            },
        )

    def current_job_state(job_id: str) -> dict:
        state = manager.read_state(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
        expires_at = _parse_time(state.get("expires_at"))
        if state.get("status") in {"succeeded", "failed"} and expires_at:
            if expires_at <= datetime.now(timezone.utc):
                job_dir = manager.job_dir(job_id)
                if job_dir:
                    shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(status_code=410, detail="El trabajo venció.")
        return state

    @application.get("/jobs/{job_id}", dependencies=[Depends(require_auth)])
    async def get_job(job_id: str) -> dict:
        return current_job_state(job_id)

    @application.get(
        "/jobs/{job_id}/artifacts/{kind}",
        dependencies=[Depends(require_auth)],
    )
    async def download_artifact(job_id: str, kind: str) -> FileResponse:
        state = current_job_state(job_id)
        if state.get("status") != "succeeded" or kind not in ARTIFACTS | LEGACY_ARTIFACTS:
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        filename = str((state.get("result") or {}).get("artifact_files", {}).get(kind, ""))
        if filename:
            _, media_type = ARTIFACTS[kind]
        else:
            filename, media_type = LEGACY_ARTIFACTS.get(kind, ("", ""))
        if not filename or Path(filename).name != filename:
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        job_dir = manager.job_dir(job_id)
        target = job_dir / "out" / filename if job_dir else None
        if not target or not target.is_file():
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        return FileResponse(target, filename=filename, media_type=media_type)

    @application.get(
        "/jobs/{job_id}/previews/{slug}",
        dependencies=[Depends(require_auth)],
    )
    async def download_preview(job_id: str, slug: str) -> FileResponse:
        state = current_job_state(job_id)
        if state.get("status") != "succeeded":
            raise HTTPException(status_code=404, detail="Vista no encontrada.")
        allowed = {
            field.get("slug")
            for field in (state.get("result") or {}).get("fields", [])
        }
        if slug not in allowed:
            raise HTTPException(status_code=404, detail="Vista no encontrada.")
        job_dir = manager.job_dir(job_id)
        target = job_dir / "out" / "mapas" / f"{slug}_preview.jpg" if job_dir else None
        if target and not target.is_file():
            target = target.with_suffix(".png")
        if not target or not target.is_file():
            raise HTTPException(status_code=404, detail="Vista no encontrada.")
        media_type = "image/jpeg" if target.suffix.lower() == ".jpg" else "image/png"
        return FileResponse(target, media_type=media_type)

    return application


app = create_app()


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
