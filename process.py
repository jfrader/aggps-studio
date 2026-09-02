#!/usr/bin/env python3
"""CLI: python process.py AgGPS.zip --out ./salida"""

from __future__ import annotations

import argparse
from pathlib import Path

from engine.languages import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from engine.pipeline import process_aggps_zip


CLI_COPY = {
    "es": ("lotes", "AGGPS", "SHAPEFILE", "PDF", "IMÁGENES", "TODO"),
    "en": ("fields", "AGGPS", "SHAPEFILE", "PDF", "IMAGES", "ALL"),
    "pt-BR": ("talhões", "AGGPS", "SHAPEFILE", "PDF", "IMAGENS", "TUDO"),
}


def main():
    p = argparse.ArgumentParser(
        description="AgGPS zip → archivos AgGPS/Shapefile + mapas de taipas"
    )
    p.add_argument("zip")
    p.add_argument("--out", default="./salida")
    p.add_argument("--no-sat", action="store_true", help="no bajar imagen satelital")
    p.add_argument(
        "--language",
        choices=SUPPORTED_LANGUAGES,
        default=DEFAULT_LANGUAGE,
        help="idioma de LEAME.txt y Mapas_choferes.pdf (default: es)",
    )
    args = p.parse_args()
    result = process_aggps_zip(
        Path(args.zip),
        Path(args.out),
        fetch_sat=not args.no_sat,
        language=args.language,
    )
    fields_label, aggps_label, shapefile_label, pdf_label, images_label, all_label = CLI_COPY[
        args.language
    ]
    print(result["title"])
    print(f"{result['n_fields']} {fields_label}")
    for f in result["fields"]:
        print(f"  {f['client']} / {f['farm']} / {f['field']}  →  {f['slug']}  {f['note']}")
    print(aggps_label, result["aggps_zip"])
    print(shapefile_label, result["shapefile_zip"])
    print(pdf_label, result["pdf"])
    print(images_label, result["images_zip"])
    print(all_label, result["bundle"])


if __name__ == "__main__":
    main()
