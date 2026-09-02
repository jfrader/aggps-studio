"""Find Client/Farm/Field folders inside an AgGPS zip extract."""

from __future__ import annotations

import re
from pathlib import Path


FIELD_MARKERS = ("Boundary.shp", "LineFeature.shp", "FieldLevel.xml")


def find_data_root(extract_dir: Path) -> Path | None:
    hits = list(extract_dir.rglob("AgGPS"))
    for hit in hits:
        data = hit / "Data"
        if data.is_dir():
            return data
    data_hits = [p for p in extract_dir.rglob("Data") if p.is_dir()]
    for d in data_hits:
        if any((fld / "Boundary.shp").exists() for fld in d.rglob("*") if fld.is_dir()):
            return d
    return None


def find_aggps_root(extract_dir: Path) -> Path | None:
    data = find_data_root(extract_dir)
    if data and data.parent.name == "AgGPS":
        return data.parent
    ag = extract_dir / "AgGPS"
    if ag.is_dir():
        return ag
    return None


def discover_fields(extract_dir: Path) -> list[dict]:
    fields: list[dict] = []
    for shp in extract_dir.rglob("Boundary.shp"):
        folder = shp.parent
        rec = _field_from_folder(folder)
        key = (rec["client"], rec["farm"], rec["field"], str(folder))
        if not any(f["_key"] == key for f in fields):
            rec["_key"] = key
            fields.append(rec)
    fields.sort(key=lambda f: (f["client"].lower(), f["farm"].lower(), f["field"].lower()))
    return fields


def _field_from_folder(folder: Path) -> dict:
    parts = list(folder.parts)
    field = folder.name
    farm = folder.parent.name if folder.parent else ""
    client = folder.parent.parent.name if folder.parent and folder.parent.parent else ""
    # Prefer names under .../Data/Client/Farm/Field
    if "Data" in parts:
        i = parts.index("Data")
        rest = parts[i + 1 :]
        if len(rest) >= 3:
            client, farm, field = rest[0], rest[1], rest[2]
        elif len(rest) == 2:
            client, farm, field = rest[0], rest[1], folder.name
        elif len(rest) == 1:
            client, farm, field = rest[0], "", folder.name
    return {
        "client": client,
        "farm": farm,
        "field": field,
        "folder": folder,
        "boundary": folder / "Boundary.shp" if (folder / "Boundary.shp").exists() else None,
        "lines": folder / "LineFeature.shp" if (folder / "LineFeature.shp").exists() else None,
        "fieldlevel": folder / "FieldLevel.xml" if (folder / "FieldLevel.xml").exists() else None,
    }


def short_name(field: str, used: set[str] | None = None, farm: str = "") -> str:
    raw = field.strip()
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", raw)
    if not cleaned:
        cleaned = "Campo"
    # "3" alone is useless — prefix farm (do before final trim to avoid overlength)
    if cleaned.isdigit() and farm:
        farm_s = re.sub(r"[^A-Za-z0-9]+", "", farm)[:6]
        cleaned = f"{farm_s}{cleaned}"
    # Keep compact Pro 700-friendly names: <=10 even after prefix
    if len(cleaned) > 10:
        cleaned = cleaned[:10]
    if used is not None:
        base = cleaned
        n = 2
        while cleaned.lower() in {u.lower() for u in used}:
            suffix = str(n)
            maxb = 10 - len(suffix)
            cleaned = f"{base[:maxb]}{suffix}"
            n += 1
        used.add(cleaned)
    return cleaned
