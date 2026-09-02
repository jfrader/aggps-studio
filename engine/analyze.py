"""Per-field stats: area, taipa count, typical ΔZ from FieldLevel survey."""

from __future__ import annotations

import math
from pathlib import Path

from . import fieldlevel, geo, shpio


def analyze_field(rec: dict) -> dict:
    out = {
        "client": rec["client"],
        "farm": rec["farm"],
        "field": rec["field"],
        "n_taipas": 0,
        "n_boundary_pts": 0,
        "area_ha": None,
        "bbox": None,
        "zmin": None,
        "zmax": None,
        "dz_cm": None,
        "note": "",
        "line_z": [],  # median z per line
        "boundary_ll": [],
        "lines_ll": [],
        "survey_llz": [],
        "origin": None,
    }

    fl = fieldlevel.parse_fieldlevel(rec["fieldlevel"]) if rec.get("fieldlevel") else None
    if fl:
        out["origin"] = (fl["lat0"], fl["lon0"], fl["alt0"])

    if rec.get("boundary") and rec["boundary"].exists():
        hdr = shpio.read_header(rec["boundary"])
        out["bbox"] = hdr["bbox"]
        rings = list(shpio.iter_parts(rec["boundary"]))
        if rings:
            ring = max(rings[0], key=len) if rings[0] else []
            out["boundary_ll"] = ring
            out["n_boundary_pts"] = len(ring)
            if fl and ring:
                out["area_ha"] = geo.shoelace_ha(ring, fl["lat0"], fl["lon0"])

    if rec.get("lines") and rec["lines"].exists():
        hdr = shpio.read_header(rec["lines"])
        if out["bbox"] is None:
            out["bbox"] = hdr["bbox"]
        else:
            xmin, ymin, xmax, ymax = out["bbox"]
            bx = hdr["bbox"]
            out["bbox"] = (min(xmin, bx[0]), min(ymin, bx[1]), max(xmax, bx[2]), max(ymax, bx[3]))
        lines = []
        for parts in shpio.iter_parts(rec["lines"]):
            for part in parts:
                if len(part) >= 2:
                    lines.append(part)
        out["lines_ll"] = lines
        out["n_taipas"] = len(lines)

    if fl and fl["survey_points"]:
        survey_llz = []
        for e, n, z in fl["survey_points"]:
            lat, lon = geo.enu_to_ll(e, n, fl["lat0"], fl["lon0"])
            survey_llz.append((lon, lat, z))
        out["survey_llz"] = survey_llz
        zs = [z for _, _, z in survey_llz]
        out["zmin"], out["zmax"] = min(zs), max(zs)

        if out["lines_ll"]:
            line_z = [_line_median_z(line, fl) for line in out["lines_ll"]]
            out["line_z"] = line_z
            valid = sorted(z for z in line_z if z is not None)
            if len(valid) >= 2:
                diffs = [abs(valid[i + 1] - valid[i]) for i in range(len(valid) - 1)]
                diffs = [d for d in diffs if 0.001 < d < 1.5]
                if diffs:
                    diffs.sort()
                    out["dz_cm"] = 100.0 * diffs[len(diffs) // 2]

    out["note"] = _note(out)
    return out


def _line_median_z(line: list[tuple[float, float]], fl: dict) -> float | None:
    """Sample a few vertices, convert to ENU, nearest survey Z."""
    pts = fl["survey_points"]
    if not pts:
        return None
    step = max(1, len(line) // 6)
    samples = []
    for lon, lat in line[::step]:
        e, n = geo.ll_to_enu(lat, lon, fl["lat0"], fl["lon0"])
        best = None
        best_d = 1e18
        for se, sn, z in pts[:: max(1, len(pts) // 400)]:
            d = (se - e) ** 2 + (sn - n) ** 2
            if d < best_d:
                best_d = d
                best = z
        if best is not None and best_d < 80 * 80:
            samples.append(best)
    if not samples:
        return None
    samples.sort()
    return samples[len(samples) // 2]


def _note(st: dict) -> str:
    n = st["n_taipas"]
    bits = [f"{n} taipas" if n else "sin taipas"]
    if st["area_ha"]:
        bits.append(f"{st['area_ha']:.2f} ha")
    if st["dz_cm"] is not None:
        bits.append(f"ΔZ mediano {st['dz_cm']:.1f} cm")
        if st["dz_cm"] >= 8:
            bits.append("terreno más inclinado")
        elif st["dz_cm"] <= 4:
            bits.append("terreno más suave")
    if st["zmin"] is not None and st["zmax"] is not None:
        bits.append(f"cota {st['zmin']:.1f}–{st['zmax']:.1f} m")
    return " · ".join(bits)
