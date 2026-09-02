"""ESRI World Imagery, square-on-ground pixels so the view is nadir (top-down)."""

from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image

ESRI = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/export"
)


@dataclass(frozen=True)
class SatelliteImage:
    image: Image.Image
    extent: tuple[float, float, float, float]


def ground_size_m(bbox) -> tuple[float, float, float]:
    xmin, ymin, xmax, ymax = bbox
    midlat = (ymin + ymax) / 2.0
    width_m = (xmax - xmin) * 111_320.0 * math.cos(math.radians(midlat))
    height_m = (ymax - ymin) * 111_320.0
    return width_m, height_m, midlat


def pixel_size(bbox, max_px: int = 1400) -> tuple[int, int]:
    width_m, height_m, _ = ground_size_m(bbox)
    width_m = max(width_m, 1.0)
    height_m = max(height_m, 1.0)
    if width_m >= height_m:
        w = max_px
        h = max(220, int(max_px * height_m / width_m))
    else:
        h = max_px
        w = max(220, int(max_px * width_m / height_m))
    return w, h


def fetch_satellite(bbox, max_px: int = 1400, timeout: int = 20) -> SatelliteImage | None:
    xmin, ymin, xmax, ymax = bbox
    w0, h0 = pixel_size(bbox, max_px)
    attempts = [(w0, h0), (min(w0, 900), min(h0, 700)), (640, max(200, int(640 * h0 / max(w0, 1))))]
    deadline = time.monotonic() + timeout * len(attempts)
    for w, h in attempts:
        params = {
            "bbox": f"{xmin},{ymin},{xmax},{ymax}",
            "bboxSR": 4326,
            "imageSR": 4326,
            "size": f"{int(w)},{int(h)}",
            "format": "jpg",
            "f": "json",
        }
        try:
            metadata_response = requests.get(
                ESRI,
                params=params,
                timeout=_remaining_timeout(deadline, timeout),
            )
            metadata_response.raise_for_status()
            metadata = metadata_response.json()
            extent_data = metadata["extent"]
            extent = tuple(float(extent_data[key]) for key in ("xmin", "ymin", "xmax", "ymax"))
            if not _valid_extent(extent):
                continue
            image_response = requests.get(
                metadata["href"],
                timeout=_remaining_timeout(deadline, timeout),
            )
            image_response.raise_for_status()
            if not image_response.content or len(image_response.content) < 800:
                continue
            image = Image.open(io.BytesIO(image_response.content)).convert("RGB")
            return SatelliteImage(image=image, extent=extent)
        except Exception:
            continue
    return None


def _valid_extent(extent: tuple[float, float, float, float]) -> bool:
    xmin, ymin, xmax, ymax = extent
    return all(math.isfinite(value) for value in extent) and xmin < xmax and ymin < ymax


def _remaining_timeout(deadline: float, per_request_timeout: int) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("satellite request deadline exceeded")
    return min(per_request_timeout, remaining)


def save_or_none(satellite: SatelliteImage | None, path: Path) -> Path | None:
    if satellite is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    satellite.image.save(path, quality=88)
    return path
