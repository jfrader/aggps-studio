"""End-to-end: AgGPS zip → tractor ZIPs + PDF + field images."""

from __future__ import annotations

import os
import re
import shutil
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

from . import analyze, basemap, discover, geo, pack, pdfmake, render
from .languages import DEFAULT_LANGUAGE, field_note, validate_language


class UnsafeArchiveError(Exception):
    """Base class for safe zip extraction failures (zip-slip, limits, encrypted, etc)."""
    pass


class ArchiveTraversalError(UnsafeArchiveError):
    """Traversal, absolute, drive letter, NUL, or symlink path in archive."""
    pass


class ArchiveEncryptedError(UnsafeArchiveError):
    """Encrypted member not allowed for safety."""
    pass


class ArchiveLimitError(UnsafeArchiveError):
    """Exceeded configurable member count, per-file, or total uncompressed size."""
    pass


def safe_extract(
    zf: zipfile.ZipFile,
    target_dir: Path | str,
    *,
    max_members: int = 2048,
    max_per_member: int = 100 * 1024 * 1024,
    max_total_uncompressed: int = 512 * 1024 * 1024,
) -> None:
    """Explicit safe extractall replacement.

    Rejects: ../ traversal, leading /, windows drives, NUL, encrypted flag, symlinks.
    Enforces limits on count, per-member uncompressed, total.
    Streams bytes and verifies actual written count matches declared file_size.
    On any failure, removes files/dirs written by this call (partial cleanup).
    """
    target = Path(target_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ValueError(f"archive target must be empty: {target}")

    infos = zf.infolist()
    if len(infos) > max_members:
        raise ArchiveLimitError(f"too many archive members: {len(infos)} > {max_members}")

    declared_total = sum(info.file_size for info in infos)
    if declared_total > max_total_uncompressed:
        raise ArchiveLimitError(
            f"total uncompressed size {declared_total} exceeds limit {max_total_uncompressed}"
        )

    written: list[Path] = []
    seen: set[str] = set()
    actual_total = 0
    try:
        for info in infos:
            name = info.filename
            if not name:
                continue
            normalized = name.replace("\\", "/")
            archive_path = PurePosixPath(normalized)
            if "\0" in name or archive_path.is_absolute() or ".." in archive_path.parts:
                raise ArchiveTraversalError(f"traversal, absolute path, or NUL: {name}")
            if re.match(r"^[A-Za-z]:", normalized):
                raise ArchiveTraversalError(f"windows drive letter: {name}")
            canonical = archive_path.as_posix().rstrip("/")
            if not canonical or canonical in seen:
                raise ArchiveTraversalError(f"empty or duplicate archive path: {name}")
            seen.add(canonical)
            if info.flag_bits & 0x0001:
                raise ArchiveEncryptedError(f"encrypted entry not allowed: {name}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ArchiveTraversalError(f"symlink entry not allowed: {name}")
            if info.file_size > max_per_member:
                raise ArchiveLimitError(f"member exceeds per-file limit: {name} ({info.file_size})")

            out_path = (target / Path(*archive_path.parts)).resolve()
            if not out_path.is_relative_to(target):
                raise ArchiveTraversalError(f"path escapes target: {name}")

            if info.is_dir():
                out_path.mkdir(parents=True, exist_ok=True)
                written.append(out_path)
                continue

            if out_path.exists():
                raise ArchiveTraversalError(f"archive path already exists: {name}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            written.append(out_path)
            written_bytes = 0
            with zf.open(info) as src, open(out_path, "wb") as dst:
                for chunk in iter(lambda: src.read(65536), b""):
                    written_bytes += len(chunk)
                    actual_total += len(chunk)
                    if written_bytes > max_per_member or actual_total > max_total_uncompressed:
                        raise ArchiveLimitError(f"streamed archive data exceeds limit at: {name}")
                    dst.write(chunk)
            if written_bytes != info.file_size:
                raise ArchiveLimitError(
                    f"streamed byte count mismatch for {name}: {written_bytes} != {info.file_size}"
                )
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        raise


def process_aggps_zip(
    zip_path: Path,
    out_dir: Path,
    fetch_sat: bool = True,
    *,
    language: str = DEFAULT_LANGUAGE,
    max_members: int = 2048,
    max_per_member: int = 100 * 1024 * 1024,
    max_total_uncompressed: int = 512 * 1024 * 1024,
) -> dict:
    """Process an AgGPS zip into tractor files and localized operator material."""
    language = validate_language(language)
    zip_path = Path(zip_path)
    out_dir = Path(out_dir)
    extract = out_dir / "_extract"
    usb = out_dir / "USB_Pro700"
    maps = out_dir / "mapas"
    for working_dir in (extract, usb, maps):
        if working_dir.exists():
            shutil.rmtree(working_dir)
    extract.mkdir(parents=True, exist_ok=True)
    maps.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as z:
        safe_extract(
            z,
            extract,
            max_members=max_members,
            max_per_member=max_per_member,
            max_total_uncompressed=max_total_uncompressed,
        )

    fields = discover.discover_fields(extract)
    if not fields:
        raise ValueError(
            "No encontré carpetas AgGPS con Boundary.shp o LineFeature.shp. "
            "El zip tiene que traer AgGPS/Data/<Grower>/<Farm>/<Campo>/."
        )

    title = _title(fields)
    prefix = _artifact_prefix(fields)
    artifact_names = {
        "aggps": f"{prefix}_AgGPS.zip",
        "shapefile": f"{prefix}_Shapefile.zip",
        "pdf": f"{prefix}_Mapas_choferes.pdf",
        "images": f"{prefix}_Mapas_lotes.zip",
        "bundle": f"{prefix}_paquete_completo.zip",
    }
    pack_info = pack.build_usb_tree(
        extract,
        fields,
        usb,
        language=language,
        artifact_names=artifact_names,
    )

    stats_list = []
    field_pages = []
    mapping = pack_info["mapping"]
    for rec, slug in mapping:
        st = analyze.analyze_field(rec)
        stats_list.append(st)
        sat = None
        if fetch_sat and st.get("bbox"):
            sat = basemap.fetch_satellite(geo.pad_bbox(st["bbox"], 0.22), max_px=1400)
        image = maps / f"{slug}_preview.jpg"
        if st.get("bbox"):
            render.render_field(st, image, satellite=sat)
        else:
            image = None
        field_pages.append(
            {"stats": st, "slug": slug, "image": image, "satellite": sat is not None}
        )

    overview_bounds = render.overview_bbox(stats_list)
    overview_satellite = None
    if fetch_sat and overview_bounds:
        overview_satellite = basemap.fetch_satellite(overview_bounds, max_px=1400)
    overview = render.render_overview(
        stats_list,
        maps / "overview.jpg",
        satellite=overview_satellite,
        paper=True,
    )

    job = {
        "title": title,
        "language": language,
        "rows": [(rec, slug, st) for (rec, slug), st in zip(mapping, stats_list)],
        "overview_image": overview,
        "overview_satellite": overview_satellite is not None,
        "field_pages": field_pages,
        "line_only": pack_info.get("line_only", []),
        "artifact_names": artifact_names,
    }
    pdf_path = out_dir / artifact_names["pdf"]
    pdfmake.build_pdf(job, pdf_path)

    aggps_zip = out_dir / artifact_names["aggps"]
    shapefile_zip = out_dir / artifact_names["shapefile"]
    images_zip = out_dir / artifact_names["images"]
    _zip_dir(usb / "A_AgGPS" / "AgGPS", aggps_zip)
    _zip_dir(usb / "B_Shapefile" / "Shapefile", shapefile_zip)
    _zip_field_images(field_pages, images_zip)

    bundle = out_dir / artifact_names["bundle"]
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(aggps_zip, aggps_zip.name)
        z.write(shapefile_zip, shapefile_zip.name)
        z.write(pdf_path, pdf_path.name)
        z.write(images_zip, images_zip.name)
        z.write(usb / "LEAME.txt", "LEAME.txt")
        z.write(usb / "INDICE_CAMPOS.txt", "INDICE_CAMPOS.txt")
    shutil.rmtree(usb, ignore_errors=True)
    shutil.rmtree(extract, ignore_errors=True)

    return {
        "n_fields": len(fields),
        "fields": [
            {
                "client": rec["client"],
                "farm": rec["farm"],
                "field": rec["field"],
                "slug": slug,
                "note": field_note(st, language),
                "n_taipas": st.get("n_taipas"),
                "area_ha": st.get("area_ha"),
                "preview": str(maps / f"{slug}_preview.jpg"),
                "satellite": page["satellite"],
            }
            for (rec, slug), st, page in zip(mapping, stats_list, field_pages)
        ],
        "aggps_zip": str(aggps_zip),
        "shapefile_zip": str(shapefile_zip),
        "pdf": str(pdf_path),
        "images_zip": str(images_zip),
        "bundle": str(bundle),
        "title": title,
        "language": language,
    }


def _title(fields: list[dict]) -> str:
    clients = sorted({f["client"] for f in fields if f["client"]})
    farms = sorted({f["farm"] for f in fields if f["farm"]})
    if len(farms) == 1 and clients:
        return f"{clients[0]}  —  {farms[0]}"
    if clients:
        return ", ".join(clients)
    return "Campos AgGPS"


def _artifact_prefix(fields: list[dict]) -> str:
    farms = sorted(
        {str(field.get("farm", "")).strip() for field in fields if field.get("farm")}
    )
    clients = sorted(
        {str(field.get("client", "")).strip() for field in fields if field.get("client")}
    )
    source = farms[0] if len(farms) == 1 else clients[0] if len(clients) == 1 else "Campos_AgGPS"
    ascii_source = (
        unicodedata.normalize("NFKD", source).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^A-Za-z0-9]+", "_", ascii_source).strip("_")[:48] or "Campos_AgGPS"


def _zip_dir(src: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(src.parent))


def _zip_field_images(field_pages: list[dict], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for page in field_pages:
            image = page.get("image")
            if image and Path(image).is_file():
                z.write(image, f"{page['slug']}.jpg")
