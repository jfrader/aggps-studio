"""Nadir / top-down field maps — same style as the conversation previews."""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors
from matplotlib.collections import LineCollection

from . import geo


IMAGERY_ATTRIBUTION = "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community"


def render_field(stats: dict, dest_image: Path, satellite=None, paper: bool = False) -> Path:
    dest_image.parent.mkdir(parents=True, exist_ok=True)
    bbox = stats.get("bbox")
    if not bbox:
        raise ValueError(f"no bbox for {stats['field']}")
    xmin, ymin, xmax, ymax = geo.pad_bbox(bbox, 0.22)
    midlat = (ymin + ymax) / 2.0
    aspect = 1.0 / max(math.cos(math.radians(midlat)), 0.2)
    width_m = (xmax - xmin) * 111_320.0 * math.cos(math.radians(midlat))
    height_m = (ymax - ymin) * 111_320.0

    line_z = stats.get("line_z") or []
    zs = [z for z in line_z if z is not None]
    norm = None
    cmap = plt.get_cmap("turbo")
    if zs:
        vmin, vmax = min(zs), max(zs)
        if vmax <= vmin:
            vmax = vmin + 0.01
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

    canvas_w, canvas_h, map_box, colorbar_box = _field_canvas(width_m, height_m, norm is not None)
    dpi = 120
    fig = plt.figure(figsize=(canvas_w / dpi, canvas_h / dpi), dpi=dpi)
    ax = fig.add_axes(_normalized_box(map_box, canvas_w, canvas_h))
    fig.patch.set_facecolor("#101214")
    ax.set_facecolor("#101214")
    txt = "#f2f2f2"

    if satellite is not None:
        ax.imshow(
            satellite.image,
            extent=_imshow_extent(satellite.extent),
            origin="upper",
            zorder=0,
            interpolation="bilinear",
        )

    survey = stats.get("survey_llz") or []
    if survey:
        step = max(1, len(survey) // 4000)
        xs = [p[0] for p in survey[::step]]
        ys = [p[1] for p in survey[::step]]
        ax.scatter(xs, ys, s=1.2, c="#d0d0d0", alpha=0.25, zorder=2, linewidths=0)

    lines = stats.get("lines_ll") or []
    segs, cols = [], []
    for i, line in enumerate(lines):
        if len(line) < 2:
            continue
        segs.append(line)
        z = line_z[i] if i < len(line_z) else None
        cols.append(cmap(norm(z)) if norm is not None and z is not None else "#f0c14b")
    if segs:
        ax.add_collection(LineCollection(segs, colors=cols, linewidths=0.85, alpha=0.95, zorder=3))

    b = stats.get("boundary_ll") or []
    if len(b) >= 3:
        xs, ys = zip(*b)
        ax.plot(xs, ys, color="#3ec6ff", lw=2.15, zorder=4)

    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect(aspect, adjustable="box")
    ax.set_axis_off()
    _scalebar(ax, xmin, ymin, xmax, ymax, midlat, color=txt)
    if satellite is not None:
        _imagery_attribution(ax)

    if norm is not None and colorbar_box is not None:
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        colorbar_ax = fig.add_axes(_normalized_box(colorbar_box, canvas_w, canvas_h))
        cb = fig.colorbar(sm, cax=colorbar_ax)
        cb.set_label("Cota (m)", color=txt, fontsize=9)
        cb.ax.yaxis.set_tick_params(color="#c8c8c8", labelcolor="#c8c8c8", labelsize=8)

    fig.savefig(
        dest_image,
        dpi=dpi,
        facecolor=fig.get_facecolor(),
        format="jpeg",
        pil_kwargs={"quality": 78, "optimize": True},
    )
    plt.close(fig)
    return dest_image


def overview_bbox(all_stats: list[dict]) -> tuple[float, float, float, float] | None:
    boxes = [stats["bbox"] for stats in all_stats if stats.get("bbox")]
    if not boxes:
        return None
    xmin = min(b[0] for b in boxes)
    ymin = min(b[1] for b in boxes)
    xmax = max(b[2] for b in boxes)
    ymax = max(b[3] for b in boxes)
    return geo.pad_bbox((xmin, ymin, xmax, ymax), 0.16)


def render_overview(all_stats: list[dict], dest_image: Path, satellite=None, paper: bool = False) -> Path | None:
    bbox = overview_bbox(all_stats)
    if not bbox:
        return None
    xmin, ymin, xmax, ymax = bbox
    midlat = (ymin + ymax) / 2.0
    aspect = 1.0 / max(math.cos(math.radians(midlat)), 0.2)

    dpi = 120
    fig, ax = plt.subplots(figsize=(1400 / dpi, 900 / dpi), dpi=dpi)
    fig.patch.set_facecolor("#101214")
    ax.set_facecolor("#101214")
    txt = "#f2f2f2"
    if satellite is not None:
        ax.imshow(
            satellite.image,
            extent=_imshow_extent(satellite.extent),
            origin="upper",
            zorder=0,
            interpolation="bilinear",
        )
    palette = ["#ff6b6b", "#4dabf7", "#69db7c", "#ffd43b", "#b197fc", "#66d9e8", "#ffa94d", "#e599f7"]
    for i, st in enumerate(all_stats):
        color = palette[i % len(palette)]
        b = st.get("boundary_ll") or []
        if len(b) >= 3:
            xs, ys = zip(*b)
            ax.plot(xs, ys, color=color, lw=1.8, label=f"{st['field']}")
        for line in (st.get("lines_ll") or [])[:: max(1, (st.get("n_taipas") or 1) // 70)]:
            if len(line) >= 2:
                xs, ys = zip(*line)
                ax.plot(xs, ys, color=color, lw=0.25, alpha=0.4)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect(aspect, adjustable="box")
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.legend(fontsize=8, loc="best", facecolor="#1b1e22", edgecolor="#333", labelcolor=txt)
    ax.set_axis_off()
    _scalebar(ax, xmin, ymin, xmax, ymax, midlat, color=txt)
    if satellite is not None:
        _imagery_attribution(ax)
    fig.tight_layout()
    dest_image.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        dest_image,
        dpi=dpi,
        facecolor=fig.get_facecolor(),
        format="jpeg",
        pil_kwargs={"quality": 78, "optimize": True},
    )
    plt.close(fig)
    return dest_image


def _field_canvas(width_m: float, height_m: float, has_colorbar: bool):
    ground_ratio = max(width_m, 1.0) / max(height_m, 1.0)
    if ground_ratio >= 1.0:
        map_w = 1210
        map_h = max(320, round(map_w / ground_ratio))
    else:
        map_h = 1280
        map_w = max(320, round(map_h * ground_ratio))

    left, bottom, top = 35, 35, 35
    colorbar_gap = 28 if has_colorbar else 0
    colorbar_w = 28 if has_colorbar else 0
    right = 55
    canvas_w = left + map_w + colorbar_gap + colorbar_w + right
    canvas_h = bottom + map_h + top
    scale = min(1.0, 1400 / max(canvas_w, canvas_h))

    def scaled(value):
        return round(value * scale)

    map_box = tuple(scaled(value) for value in (left, bottom, map_w, map_h))
    colorbar_box = None
    if has_colorbar:
        colorbar_box = tuple(
            scaled(value)
            for value in (left + map_w + colorbar_gap, bottom, colorbar_w, map_h)
        )
    return scaled(canvas_w), scaled(canvas_h), map_box, colorbar_box


def _normalized_box(box, canvas_w: int, canvas_h: int):
    x, y, width, height = box
    return [x / canvas_w, y / canvas_h, width / canvas_w, height / canvas_h]


def _imshow_extent(bbox):
    xmin, ymin, xmax, ymax = bbox
    return xmin, xmax, ymin, ymax


def _scalebar(ax, xmin, ymin, xmax, ymax, midlat, color="white"):
    width_m = (xmax - xmin) * 111_320.0 * math.cos(math.radians(midlat))
    nice = 50
    for cand in (50, 100, 200, 300, 400, 500, 1000, 2000, 5000):
        if cand < width_m * 0.28:
            nice = cand
    dlon = nice / (111_320.0 * math.cos(math.radians(midlat)))
    x0 = xmin + (xmax - xmin) * 0.06
    y0 = ymin + (ymax - ymin) * 0.07
    ax.plot([x0, x0 + dlon], [y0, y0], color=color, lw=3.2, solid_capstyle="butt", zorder=6)
    ax.text(
        x0 + dlon / 2,
        y0 + (ymax - ymin) * 0.012,
        f"{nice} m",
        color=color,
        ha="center",
        va="bottom",
        fontsize=8,
    )


def _imagery_attribution(ax) -> None:
    ax.text(
        0.99,
        0.01,
        IMAGERY_ATTRIBUTION,
        transform=ax.transAxes,
        color="#f2f2f2",
        ha="right",
        va="bottom",
        fontsize=5.5,
        zorder=7,
        clip_on=False,
        bbox={"boxstyle": "square,pad=0.2", "facecolor": "#101214", "edgecolor": "none", "alpha": 0.78},
    )
