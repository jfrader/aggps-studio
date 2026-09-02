#!/usr/bin/env python3
"""Fallback converter when AgGPS Studio is down (stdlib only, safe extract).

Emits the CURRENT direct farm-prefixed deliverables per contract:
  <Farm>_AgGPS.zip     (top-level AgGPS/ ; pruned)
  <Farm>_Shapefile.zip (top-level Shapefile/ ; only 2D bdy+line for tractor fields)
+ LEAME.txt + INDICE_CAMPOS.txt beside them.
Never emits USB_Pro700/ A_AgGPS/ B_Shapefile/ .
Prunes SurveyPoints*, Z*, .prj, .cpg per safety rules; keeps line-only + permitted bytes.
--maps errors (unsupported here).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import struct
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

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


def is_z_shape_type(typ: str | int) -> bool:
    if isinstance(typ, int):
        return typ in (11, 13, 15)
    return "Z" in str(typ)

LEAME = """AFS Pro 700 - USB AgGPS (fallback directo)
==============================================

El monitor mira la RAIZ del pendrive. Extraiga UN ZIP y copie UNA carpeta
al lado del .cn1 del tractor (no adentro, no formatee ese palo):

  <Farm>_AgGPS.zip     -> extrae AgGPS/     -> Import2 -> Source = Non Pro 700 1
  <Farm>_Shapefile.zip -> extrae Shapefile/ -> Import2 -> Source = Shapefile

Pendrive FAT32. Los ZIPs se abren directamente a la carpeta lista para copiar.
NO copie la estructura USB_Pro700 ni A_/B_ wrappers (ya no se generan).

------------------------------------------------
FORMA A (recomendada) - mismo palo del tractor
------------------------------------------------
Despues de extraer <Farm>_AgGPS.zip debe quedar:

  E:\\<algo>.cn1\\
  E:\\AgGPS\\Data\\<Grower>\\<Farm>\\<Campo>\\Boundary.shp
  E:\\AgGPS\\Data\\<Grower>\\<Farm>\\<Campo>\\LineFeature.shp

1. Apagar. Sacar el palo. Copiar AgGPS al lado del .cn1. Volver a poner. Encender.
2. Esperar el cartel de copia a memoria interna.
3. Data Management -> Import2 -> Source = Non Pro 700 1
4. Importar UN campo primero. Boundary, despues taipas (Guidance / Line).

Alternativa Case (otro palo, sin .cn1): encender con el palo de datos,
esperar copia, apagar, volver a poner el palo original con .cn1, Import2.
Un palo sin .cn1 dejado en el monitor no es solo mas lento: puede no
tener Grower/Farm/Field.

------------------------------------------------
FORMA B - carpeta Shapefile
------------------------------------------------
Despues de extraer <Farm>_Shapefile.zip:

  E:\\<algo>.cn1\\
  E:\\Shapefile\\<Slug>_Bdy.shp
  E:\\Shapefile\\<Slug>_Taipa.shp

Import2 -> Source = Shapefile
1. *_Bdy   -> Data Type = Boundary
2. *_Taipa -> Data Type = Guidance / Line / Multiswath

Las taipas NUNCA disparan auto-select. Eso lo hace el poligono Boundary.
El tractor tiene que estar FISICAMENTE dentro de ese poligono.

NO copie SurveyPoints, Z, .prj, .cpg. NO mezcle AgGPS y Shapefile en el mismo palo.
NO mueva coordenadas para calzar la foto satelital.
"""


def shp_header(path: Path) -> dict:
    with open(path, "rb") as f:
        hdr = f.read(100)
    if len(hdr) < 100:
        raise ValueError(f"shapefile too small: {path}")
    typ = struct.unpack("<i", hdr[32:36])[0]
    bbox = struct.unpack("<4d", hdr[36:68])
    return {"type": SHP_TYPES.get(typ, typ), "type_code": typ, "bbox": bbox}


def copy_sidecars(src_shp: Path, dest_shp: Path) -> None:
    dest_shp.parent.mkdir(parents=True, exist_ok=True)
    for ext in (".shp", ".shx", ".dbf"):
        source = src_shp.with_suffix(ext)
        if source.exists():
            dest_shp.with_suffix(ext).write_bytes(source.read_bytes())


def _pruned_copy_aggps(src: Path, dst: Path) -> None:
    """Copy Trimble AgGPS tree preserving byte-identical Boundary/LineFeature,
    but prune SurveyPoints* families, Z shapefile families +sidecars, .prj/.cpg.
    Line-only folders are preserved. Stdlib only.
    """
    dst.mkdir(parents=True, exist_ok=True)
    # identify Z shape bases (by header type) to skip whole family
    z_bases: set[tuple[Path, str]] = set()
    for shp in (path for path in src.rglob("*") if path.is_file() and path.suffix.lower() == ".shp"):
        try:
            hdr = shp_header(shp)
            if is_z_shape_type(hdr.get("type") or hdr.get("type_code", 0)):
                rel_parent = shp.parent.relative_to(src)
                z_bases.add((rel_parent, shp.stem.lower()))
        except Exception:
            # malformed shp: treat as z-unsafe for safety
            rel_parent = shp.parent.relative_to(src)
            z_bases.add((rel_parent, shp.stem.lower()))

    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        # case-insensitive SurveyPoints anywhere in path
        if any(part.lower().startswith("surveypoints") for part in rel.parts):
            continue
        name_l = p.name.lower()
        # always drop .prj .cpg sidecars
        if name_l.endswith((".prj", ".cpg")):
            continue
        # drop if part of Z family
        stem_l = p.stem.lower()
        if (rel.parent, stem_l) in z_bases:
            continue
        dstd = dst / rel
        dstd.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dstd)


def find_aggps_root(extract: Path) -> Path | None:
    for hit in extract.rglob("AgGPS"):
        if (hit / "Data").is_dir():
            return hit
    return None


def field_names(folder: Path) -> tuple[str, str, str]:
    parts = list(folder.parts)
    field = folder.name
    farm = folder.parent.name if folder.parent else ""
    client = folder.parent.parent.name if folder.parent and folder.parent.parent else ""
    if "Data" in parts:
        rest = parts[parts.index("Data") + 1 :]
        if len(rest) >= 3:
            client, farm, field = rest[0], rest[1], rest[2]
        elif len(rest) == 2:
            client, farm, field = rest[0], rest[1], folder.name
        elif len(rest) == 1:
            client, farm, field = rest[0], "", folder.name
    return client, farm, field


def short_name(field: str, used: set[str], farm: str = "") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", field.strip()) or "Campo"
    if len(cleaned) > 10:
        cleaned = cleaned[:10]
    if cleaned.isdigit() and farm:
        cleaned = f"{re.sub(r'[^A-Za-z0-9]+', '', farm)[:6]}{cleaned}"
    base = cleaned
    number = 2
    while cleaned.lower() in {used_name.lower() for used_name in used}:
        cleaned = f"{base[:8]}{number}"
        number += 1
    used.add(cleaned)
    return cleaned


def artifact_prefix(fields: list[dict]) -> str:
    """Farm (or client) based ASCII prefix like production, for <Farm>_AgGPS.zip"""
    farms = sorted({str(f.get("farm", "")).strip() for f in fields if f.get("farm")})
    clients = sorted({str(f.get("client", "")).strip() for f in fields if f.get("client")})
    source = farms[0] if len(farms) == 1 else (clients[0] if len(clients) == 1 else "Campos_AgGPS")
    ascii_source = unicodedata.normalize("NFKD", source).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "_", ascii_source).strip("_")[:48] or "Campos_AgGPS"


def discover_tractor_fields(extract: Path) -> tuple[list[dict], list[Path]]:
    """Tractor field = Boundary + LineFeature. Line-only listed separately."""
    fields: list[dict] = []
    line_only: list[Path] = []
    seen: set[Path] = set()
    for shp in extract.rglob("Boundary.shp"):
        folder = shp.parent
        if folder in seen:
            continue
        seen.add(folder)
        lines = folder / "LineFeature.shp"
        client, farm, field = field_names(folder)
        record = {
            "client": client,
            "farm": farm,
            "field": field,
            "folder": folder,
            "boundary": shp,
            "lines": lines if lines.exists() else None,
            "fieldlevel": folder / "FieldLevel.xml" if (folder / "FieldLevel.xml").exists() else None,
        }
        if record["lines"]:
            fields.append(record)
    for shp in extract.rglob("LineFeature.shp"):
        folder = shp.parent
        if not (folder / "Boundary.shp").exists():
            line_only.append(folder)
    fields.sort(key=lambda item: (item["client"].lower(), item["farm"].lower(), item["field"].lower()))
    return fields, line_only


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_zip(zip_path: Path, dest: Path) -> Path:
    """Hardened stdlib extract for fallback (no customer data, no engine touch).
    Rejects: encrypted, symlinks, duplicate normalized names, absolute/drive-qualified paths,
    traversal, and missing required .shx/.dbf sidecars for any .shp member.
    Preflight before extractall; keeps prior output contract for direct AgGPS/Shapefile zips.
    """
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        names = [info.filename.replace("\\", "/") for info in infos]

        # duplicate normalized
        seen: set[str] = set()
        for n in names:
            if not n:
                continue
            norm = n.lower().rstrip("/")
            if norm in seen:
                raise SystemExit(f"duplicate normalized archive path: {n}")
            seen.add(norm)

        for n in names:
            if not n:
                continue
            p = PurePosixPath(n)
            if n.startswith("/") or p.is_absolute() or ".." in p.parts or "\0" in n:
                raise SystemExit(f"refusing zip member (traversal/absolute/NUL): {n}")
            # drive-qualified e.g. C: or c:/
            if re.match(r"^[A-Za-z]:", n.replace("\\", "/")):
                raise SystemExit(f"refusing zip member (drive letter): {n}")

        # encrypted and symlinks
        for info in infos:
            if info.flag_bits & 0x0001:
                raise SystemExit(f"encrypted member not allowed: {info.filename}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise SystemExit(f"symlink entry not allowed: {info.filename}")

        # sidecar requirement: every .shp must have sibling .shx and .dbf in the archive
        member_lower = {nn.lower() for nn in names}
        for n in names:
            if n.lower().endswith(".shp"):
                base = n[:-4]
                for ext in (".shx", ".dbf"):
                    side = (base + ext).lower()
                    if side not in member_lower:
                        raise SystemExit(f"missing required sidecar {ext} for shapefile member: {n}")

        archive.extractall(dest)
    return dest


def build_direct(extract: Path, out: Path) -> list[dict]:
    """Emit the CURRENT direct-root farm-prefixed deliverables:
    <prefix>_AgGPS.zip (opens directly to AgGPS/)
    <prefix>_Shapefile.zip (opens directly to Shapefile/)
    Plus LEAME.txt and INDICE_CAMPOS.txt beside them.
    Prunes forbidden members in AgGPS tree per safety rules.
    Shapefile zip only .shp/.shx/.dbf 2D for boundary-backed fields.
    Never emits USB_Pro700/A_AgGPS/B_Shapefile wrappers.
    """
    fields, line_only = discover_tractor_fields(extract)
    if not fields:
        raise SystemExit("no tractor fields (Boundary.shp + LineFeature.shp)")

    prefix = artifact_prefix(fields)
    ag_zip = out / f"{prefix}_AgGPS.zip"
    shp_zip = out / f"{prefix}_Shapefile.zip"

    out.mkdir(parents=True, exist_ok=True)
    # write txts beside zips (exact names)
    (out / "LEAME.txt").write_text(LEAME, encoding="utf-8")

    ag_src = find_aggps_root(extract)
    if not ag_src:
        raise SystemExit("no AgGPS/Data tree in the zip")

    # prepare pruned AgGPS tree in temp, zip so top-level is AgGPS/
    with tempfile.TemporaryDirectory(prefix="aggps-fallback-ag-") as td:
        pruned = Path(td) / "AgGPS"
        _pruned_copy_aggps(ag_src, pruned)
        # zip with entries starting at AgGPS/ (relative_to parent of pruned)
        ag_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ag_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(pruned.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(pruned.parent))

    # Shapefile only 2D for tractor fields, .shp shx dbf only
    used: set[str] = set()
    rows = ["Grower\tFarm\tField\tUSB_name\tBoundary\tTaipas"]
    mapping = []
    with tempfile.TemporaryDirectory(prefix="aggps-fallback-shp-") as td:
        shp_root = Path(td) / "Shapefile"
        shp_root.mkdir(parents=True)
        for record in fields:
            boundary = shp_header(record["boundary"])
            lines = shp_header(record["lines"])
            if boundary["type"] != "Polygon":
                raise SystemExit(f"{record['field']} Boundary is {boundary['type']}, need 2D Polygon")
            if lines["type"] != "Polyline":
                raise SystemExit(f"{record['field']} LineFeature is {lines['type']}, need 2D Polyline")
            slug = short_name(record["field"], used, farm=record["farm"])
            copy_sidecars(record["boundary"], shp_root / f"{slug}_Bdy.shp")
            copy_sidecars(record["lines"], shp_root / f"{slug}_Taipa.shp")
            if sha256(record["boundary"]) != sha256(shp_root / f"{slug}_Bdy.shp"):
                raise SystemExit(f"byte mismatch after copy: {record['field']}")
            rows.append(f"{record['client']}\t{record['farm']}\t{record['field']}\t{slug}\tyes\tyes")
            mapping.append({**record, "slug": slug, "bdy_type": boundary["type"], "lin_type": lines["type"]})

        shp_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(shp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(shp_root.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(shp_root.parent))

    (out / "INDICE_CAMPOS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

    print(f"tractor fields: {len(fields)}")
    print(f"line-only kept in AgGPS tree only: {len(line_only)}")
    for record in mapping:
        print(f"  {record['field']!r} -> {record['slug']}")
    print(f"wrote {ag_zip}")
    print(f"wrote {shp_zip}")
    print(f"wrote {(out / 'LEAME.txt')} and {(out / 'INDICE_CAMPOS.txt')}")
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description="AgGPS zip -> direct <Farm>_AgGPS.zip + <Farm>_Shapefile.zip (Pro 700 compatible, no wrappers)")
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("-o", "--out", type=Path, default=Path("aggps_fallback_out"))
    parser.add_argument("--maps", action="store_true", help="unsupported in fallback (no PDF or map generation)")
    args = parser.parse_args()
    if not args.zip_path.exists():
        raise SystemExit(f"missing {args.zip_path}")
    if args.maps:
        raise SystemExit("--maps is unsupported in this fallback converter (use full AgGPS Studio for PDF/maps)")

    work = args.out / "_extract"
    if work.exists():
        shutil.rmtree(work)
    extract_zip(args.zip_path, work)
    build_direct(work, args.out)
    shutil.rmtree(work, ignore_errors=True)
    print("fallback complete (direct-root zips + LEAME/INDICE beside; CRC-safe, pruned)")


if __name__ == "__main__":
    main()
