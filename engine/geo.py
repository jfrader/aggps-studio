"""Local ENU (FieldLevel metres) ↔ WGS84."""

from __future__ import annotations

import math

R_EARTH = 6378137.0


def enu_to_ll(e: float, n: float, lat0: float, lon0: float) -> tuple[float, float]:
    lat = lat0 + (n / R_EARTH) * (180.0 / math.pi)
    lon = lon0 + (e / (R_EARTH * math.cos(math.radians(lat0)))) * (180.0 / math.pi)
    return lat, lon


def ll_to_enu(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    n = (lat - lat0) * math.pi / 180.0 * R_EARTH
    e = (lon - lon0) * math.pi / 180.0 * R_EARTH * math.cos(math.radians(lat0))
    return e, n


def shoelace_ha(lonlat: list[tuple[float, float]], lat0: float, lon0: float) -> float:
    if len(lonlat) < 4:
        return 0.0
    pts = [ll_to_enu(lat, lon, lat0, lon0) for lon, lat in lonlat]
    area = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0 / 10_000.0


def pad_bbox(bbox: tuple[float, float, float, float], frac: float = 0.08):
    xmin, ymin, xmax, ymax = bbox
    dx = max(xmax - xmin, 1e-5)
    dy = max(ymax - ymin, 1e-5)
    return (xmin - dx * frac, ymin - dy * frac, xmax + dx * frac, ymax + dy * frac)
