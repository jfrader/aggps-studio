"""Minimal shapefile reader + sidecar copy. No pyshp required."""

from __future__ import annotations

import math
import shutil
import struct
from pathlib import Path

SHP_TYPES = {
    0: "Null",
    1: "Point",
    3: "Polyline",
    5: "Polygon",
    8: "MultiPoint",
    11: "PointZ",
    13: "PolylineZ",
    15: "PolygonZ",
}


def read_header(path: Path) -> dict:
    with open(path, "rb") as f:
        hdr = f.read(100)
    if len(hdr) < 100:
        raise ValueError(f"shapefile too small: {path}")
    code = struct.unpack(">i", hdr[:4])[0]
    if code != 9994:
        raise ValueError(f"invalid shapefile magic number {code} (expected 9994): {path}")
    ver = struct.unpack("<i", hdr[28:32])[0]
    if ver != 1000:
        raise ValueError(f"invalid shapefile version {ver} (expected 1000): {path}")
    declared_size = struct.unpack(">i", hdr[24:28])[0] * 2
    actual_size = path.stat().st_size
    if declared_size < 100 or declared_size != actual_size:
        raise ValueError(
            f"shapefile size does not match its header ({declared_size} != {actual_size}): {path}"
        )
    typ = struct.unpack("<i", hdr[32:36])[0]
    xmin, ymin, xmax, ymax = struct.unpack("<4d", hdr[36:68])
    if not all(math.isfinite(value) for value in (xmin, ymin, xmax, ymax)):
        raise ValueError(f"invalid non-finite shapefile bounds: {path}")
    if xmin > xmax or ymin > ymax:
        raise ValueError(f"invalid shapefile bounds order: {path}")
    return {
        "code": code,
        "type": SHP_TYPES.get(typ, typ),
        "type_code": typ,
        "bbox": (xmin, ymin, xmax, ymax),
    }


def is_z_shape_type(typ: str | int) -> bool:
    if isinstance(typ, int):
        return typ in (11, 13, 15)
    return isinstance(typ, str) and typ.endswith("Z")


def validate_shape_role(shp_path: Path, role: str) -> dict:
    """Strictly require .shp/.shx/.dbf and exact 2D role type; also magic/version via read_header."""
    if role not in ("Boundary", "LineFeature"):
        raise ValueError(f"unknown role: {role}")
    if not shp_path.exists():
        raise ValueError(f"missing required {role}.shp: {shp_path}")
    for ext in (".shp", ".shx", ".dbf"):
        side = shp_path.with_suffix(ext)
        if not side.exists():
            raise ValueError(f"{role} requires {ext} sidecar: {side}")
        if side.stat().st_size == 0:
            raise ValueError(f"{role} has empty {ext} sidecar: {side}")
    hdr = read_header(shp_path)
    expected = "Polygon" if role == "Boundary" else "Polyline"
    if hdr["type"] != expected:
        raise ValueError(f"{role} must be exactly {expected}, got {hdr['type']}: {shp_path}")
    index_hdr = read_header(shp_path.with_suffix(".shx"))
    if index_hdr["type_code"] != hdr["type_code"]:
        raise ValueError(f"{role} .shx shape type does not match .shp: {shp_path}")
    _validate_dbf(shp_path.with_suffix(".dbf"), role)
    parts = next(iter_parts(shp_path), None)
    if not parts:
        raise ValueError(f"{role} contains no geometry: {shp_path}")
    if role == "Boundary":
        if not any(len(ring) >= 4 and ring[0] == ring[-1] for ring in parts):
            raise ValueError(f"Boundary must contain a closed polygon ring: {shp_path}")
    elif not any(len(line) >= 2 for line in parts):
        raise ValueError(f"LineFeature must contain a polyline: {shp_path}")
    return hdr


def _validate_dbf(path: Path, role: str) -> None:
    size = path.stat().st_size
    with open(path, "rb") as dbf:
        header = dbf.read(32)
    if len(header) != 32:
        raise ValueError(f"{role} has a truncated .dbf header: {path}")
    record_count = struct.unpack("<I", header[4:8])[0]
    header_size = struct.unpack("<H", header[8:10])[0]
    record_size = struct.unpack("<H", header[10:12])[0]
    if header_size < 33 or record_size < 1 or header_size > size:
        raise ValueError(f"{role} has invalid .dbf dimensions: {path}")
    if header_size + record_count * record_size > size:
        raise ValueError(f"{role} has truncated .dbf records: {path}")


def iter_parts(path: Path):
    """Yield lists of (x, y) rings/parts. x=lon, y=lat for WGS84 AgGPS files."""
    with open(path, "rb") as f:
        f.read(100)
        while True:
            rh = f.read(8)
            if len(rh) < 8:
                break
            rec_len = struct.unpack(">i", rh[4:8])[0]
            if rec_len < 2:
                raise ValueError(f"invalid shapefile record length: {path}")
            data = f.read(rec_len * 2)
            if len(data) != rec_len * 2:
                raise ValueError(f"truncated shapefile record: {path}")
            st = struct.unpack("<i", data[0:4])[0]
            if st not in (3, 5, 13, 15):
                continue
            off = 4 + 32
            if len(data) < off + 8:
                raise ValueError(f"truncated shapefile geometry header: {path}")
            nparts, npts = struct.unpack("<2i", data[off : off + 8])
            off += 8
            if nparts < 1 or npts < 1:
                raise ValueError(f"invalid shapefile geometry counts: {path}")
            parts_end = off + 4 * nparts
            points_end = parts_end + 16 * npts
            if parts_end > len(data) or points_end > len(data):
                raise ValueError(f"shapefile geometry exceeds its record: {path}")
            parts = struct.unpack(f"<{nparts}i", data[off : off + 4 * nparts])
            if parts[0] != 0 or any(
                start < 0 or start >= npts or (i and start <= parts[i - 1])
                for i, start in enumerate(parts)
            ):
                raise ValueError(f"invalid shapefile part indexes: {path}")
            off = parts_end
            pts = list(struct.iter_unpack("<2d", data[off : off + 16 * npts]))
            if not all(math.isfinite(value) for point in pts for value in point):
                raise ValueError(f"non-finite shapefile coordinate: {path}")
            rings = []
            for i, start in enumerate(parts):
                end = parts[i + 1] if i + 1 < len(parts) else npts
                rings.append([(p[0], p[1]) for p in pts[start:end]])
            yield rings


def copy_sidecars(src_shp: Path, dest_shp: Path, exts=(".shp", ".shx", ".dbf")) -> None:
    dest_shp.parent.mkdir(parents=True, exist_ok=True)
    for ext in exts:
        s = src_shp.with_suffix(ext)
        if not s.is_file():
            raise ValueError(f"missing required shapefile sidecar: {s}")
        shutil.copyfile(s, dest_shp.with_suffix(ext))
