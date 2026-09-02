"""Supported languages for generated operator material."""

from __future__ import annotations


DEFAULT_LANGUAGE = "es"
SUPPORTED_LANGUAGES = ("es", "en", "pt-BR")

FIELD_NOTE_COPY = {
    "es": {
        "none": "sin taipas",
        "count": "{count} taipas",
        "median": "ΔZ mediano",
        "steep": "terreno más inclinado",
        "gentle": "terreno más suave",
        "elevation": "cota {zmin:.1f}–{zmax:.1f} m",
    },
    "en": {
        "none": "no taipa lines",
        "count": "{count} taipa lines",
        "median": "median ΔZ",
        "steep": "steeper terrain",
        "gentle": "gentler terrain",
        "elevation": "elevation {zmin:.1f}–{zmax:.1f} m",
    },
    "pt-BR": {
        "none": "sem taipas",
        "count": "{count} taipas",
        "median": "ΔZ mediano",
        "steep": "terreno mais inclinado",
        "gentle": "terreno mais suave",
        "elevation": "cota {zmin:.1f}–{zmax:.1f} m",
    },
}


def validate_language(language: str) -> str:
    if language not in SUPPORTED_LANGUAGES:
        choices = ", ".join(SUPPORTED_LANGUAGES)
        raise ValueError(f"unsupported operator language: {language!r}; choose {choices}")
    return language


def field_note(stats: dict, language: str = DEFAULT_LANGUAGE) -> str:
    copy = FIELD_NOTE_COPY[validate_language(language)]
    count = int(stats.get("n_taipas") or 0)
    bits = [copy["count"].format(count=count) if count else copy["none"]]
    if stats.get("area_ha") is not None:
        bits.append(f"{stats['area_ha']:.2f} ha")
    if stats.get("dz_cm") is not None:
        bits.append(f"{copy['median']} {stats['dz_cm']:.1f} cm")
        if stats["dz_cm"] >= 8:
            bits.append(copy["steep"])
        elif stats["dz_cm"] <= 4:
            bits.append(copy["gentle"])
    if stats.get("zmin") is not None and stats.get("zmax") is not None:
        bits.append(copy["elevation"].format(zmin=stats["zmin"], zmax=stats["zmax"]))
    return " · ".join(bits)
