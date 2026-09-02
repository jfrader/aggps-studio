"""Parse Trimble FieldLevel.xml (origin + survey points + xml boundary)."""

from __future__ import annotations

import re
from pathlib import Path


def _floats(tag: str, text: str) -> list[float]:
    return [float(x) for x in re.findall(rf"<{tag}>\s*([^<]+)\s*</{tag}>", text)]


def parse_fieldlevel(path: Path) -> dict | None:
    if not path.exists():
        return None
    text = path.read_text(errors="replace")
    origin = re.search(
        r"<origin\s+lat='([^']+)'\s+lon='([^']+)'\s+alt='([^']+)'",
        text,
    )
    if not origin:
        origin = re.search(
            r'<origin\s+lat="([^"]+)"\s+lon="([^"]+)"\s+alt="([^"]+)"',
            text,
        )
    if not origin:
        return None
    lat0, lon0, alt0 = (float(origin.group(1)), float(origin.group(2)), float(origin.group(3)))

    def section_pts(label: str) -> list[tuple[float, float, float]]:
        m = re.search(rf"<{label}>(.*?)</{label}>", text, re.S)
        if not m:
            return []
        block = m.group(1)
        xs, ys, zs = _floats("x", block), _floats("y", block), _floats("z", block)
        n = min(len(xs), len(ys), len(zs))
        return list(zip(xs[:n], ys[:n], zs[:n]))

    return {
        "lat0": lat0,
        "lon0": lon0,
        "alt0": alt0,
        "boundary": section_pts("boundary"),
        "survey_points": section_pts("survey_points"),
    }
