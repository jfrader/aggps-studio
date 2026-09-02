"""Printable driver booklet (A4 landscape) with maps + USB cheat-sheet."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from PIL import Image

from .languages import DEFAULT_LANGUAGE, field_note, validate_language


PAGE = landscape(A4)
MAX_MAP_BYTES = 750 * 1024
MAX_MAP_PX = 1400
INDEX_ROWS_PER_PAGE = 24

PDF_COPY = {
    "es": {
        "title": "Mapas de taipas",
        "brand": "AgGPS Studio  ·  mapas para el tractor",
        "printed": "Impreso",
        "fields": "Campos",
        "index": "Índice completo de lotes",
        "index_more": "El índice continúa en la página siguiente.",
        "cover_footer": "Boundary = límite del lote (auto-select GPS).   Taipas = líneas.   Pendrive FAT32.",
        "index_continued": "Índice de lotes — continuación",
        "no_area": "sin área",
        "howto": "Cómo cargar en el AFS Pro 700",
        "overview": "Vista general",
        "no_satellite": "sin satélite",
        "field_data": "DATOS DEL LOTE",
        "taipas": "Taipas",
        "area": "Superficie",
        "median_dz": "ΔZ mediano",
        "elevations": "Cotas",
        "overview_footer": "Límites de colores = polígonos GPS del cliente. La foto es fondo.",
        "field_footer": "Límite cyan = polígono GPS del cliente. La foto es fondo.",
        "fixed_geometry": "No se mueve el shapefile para calzar la imagen.",
        "test_field": "un lote",
    },
    "en": {
        "title": "Taipa maps",
        "brand": "AgGPS Studio  ·  tractor maps",
        "printed": "Printed",
        "fields": "Fields",
        "index": "Complete field index",
        "index_more": "The index continues on the next page.",
        "cover_footer": "Boundary = field boundary (GPS auto-select).   Taipas = lines.   FAT32 USB drive.",
        "index_continued": "Field index — continued",
        "no_area": "no area",
        "howto": "How to load the AFS Pro 700",
        "overview": "Overview",
        "no_satellite": "no satellite",
        "field_data": "FIELD DATA",
        "taipas": "Taipa lines",
        "area": "Area",
        "median_dz": "Median ΔZ",
        "elevations": "Elevations",
        "overview_footer": "Colored boundaries = client GPS polygons. The photo is background only.",
        "field_footer": "Cyan boundary = client GPS polygon. The photo is background only.",
        "fixed_geometry": "The shapefile is never moved to fit the image.",
        "test_field": "one field",
    },
    "pt-BR": {
        "title": "Mapas de taipas",
        "brand": "AgGPS Studio  ·  mapas para o trator",
        "printed": "Impresso",
        "fields": "Talhões",
        "index": "Índice completo de talhões",
        "index_more": "O índice continua na próxima página.",
        "cover_footer": "Boundary = limite do talhão (seleção por GPS).   Taipas = linhas.   Pendrive FAT32.",
        "index_continued": "Índice de talhões — continuação",
        "no_area": "sem área",
        "howto": "Como carregar no AFS Pro 700",
        "overview": "Visão geral",
        "no_satellite": "sem satélite",
        "field_data": "DADOS DO TALHÃO",
        "taipas": "Taipas",
        "area": "Área",
        "median_dz": "ΔZ mediano",
        "elevations": "Cotas",
        "overview_footer": "Limites coloridos = polígonos GPS do cliente. A foto é apenas fundo.",
        "field_footer": "Limite ciano = polígono GPS do cliente. A foto é apenas fundo.",
        "fixed_geometry": "O shapefile nunca é movido para ajustar à imagem.",
        "test_field": "um talhão",
    },
}


def build_pdf(job: dict, dest: Path) -> Path:
    language = validate_language(str(job.get("language") or DEFAULT_LANGUAGE))
    copy = PDF_COPY[language]
    dest.parent.mkdir(parents=True, exist_ok=True)
    _validate_map_images(job)
    c = canvas.Canvas(str(dest), pagesize=PAGE)
    c.setTitle(f"{copy['title']} — {job.get('title', 'AgGPS')}")
    rows = list(job.get("rows") or [])
    show_context = len({(rec["client"], rec["farm"]) for rec, _, _ in rows}) > 1
    _cover(
        c,
        job,
        rows[:INDEX_ROWS_PER_PAGE],
        len(rows) > INDEX_ROWS_PER_PAGE,
        show_context,
        language,
    )
    for start in range(INDEX_ROWS_PER_PAGE, len(rows), INDEX_ROWS_PER_PAGE):
        _index_page(c, rows[start : start + INDEX_ROWS_PER_PAGE], show_context, language)
    _howto(c, job, language)
    ov = job.get("overview_image")
    if ov and Path(ov).exists():
        _image_page(
            c,
            Path(ov),
            copy["overview"],
            job.get("title", ""),
            satellite=bool(job.get("overview_satellite")),
            language=language,
        )
    for page in job.get("field_pages") or []:
        _field_page(c, page, language)
    c.save()
    return dest


def _cover(
    c: canvas.Canvas,
    job: dict,
    rows: list,
    has_more: bool,
    show_context: bool,
    language: str,
):
    copy = PDF_COPY[language]
    w, h = PAGE
    c.setFillColorRGB(0.07, 0.12, 0.10)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColorRGB(0.94, 0.86, 0.45)
    c.rect(0, h - 18 * mm, w, 18 * mm, fill=1, stroke=0)
    c.setFillColorRGB(0.12, 0.12, 0.10)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(18 * mm, h - 12 * mm, copy["brand"])
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(18 * mm, h - 48 * mm, job.get("title") or copy["fields"])
    c.setFont("Helvetica", 12)
    c.drawString(18 * mm, h - 60 * mm, datetime.now().strftime(f"{copy['printed']} %Y-%m-%d  %H:%M"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(18 * mm, h - 78 * mm, copy["index"])
    _draw_index(
        c,
        rows,
        h - 90 * mm,
        dark_background=True,
        show_context=show_context,
        language=language,
    )
    if has_more:
        c.setFont("Helvetica-Oblique", 8)
        c.drawRightString(w - 18 * mm, 25 * mm, copy["index_more"])
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColorRGB(0.80, 0.80, 0.72)
    c.drawString(18 * mm, 16 * mm, copy["cover_footer"])
    c.showPage()


def _index_page(c: canvas.Canvas, rows: list, show_context: bool, language: str):
    w, h = PAGE
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColorRGB(0.12, 0.12, 0.10)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(18 * mm, h - 20 * mm, PDF_COPY[language]["index_continued"])
    _draw_index(c, rows, h - 36 * mm, show_context=show_context, language=language)
    c.showPage()


def _draw_index(
    c: canvas.Canvas,
    rows: list,
    start_y,
    *,
    dark_background: bool = False,
    show_context: bool = False,
    language: str = DEFAULT_LANGUAGE,
):
    column_x = (18 * mm, 153 * mm)
    rows_per_column = 12
    for index, (rec, slug, stats) in enumerate(rows):
        column = index // rows_per_column
        row = index % rows_per_column
        if column >= len(column_x):
            break
        x = column_x[column]
        y = start_y - row * 7.2 * mm
        area = stats.get("area_ha")
        area_text = f"{area:.2f} ha" if area is not None else PDF_COPY[language]["no_area"]
        if dark_background:
            c.setFillColorRGB(0.90, 0.90, 0.82)
        else:
            c.setFillColorRGB(0.12, 0.12, 0.10)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(x, y, str(rec["field"])[:18])
        if show_context:
            c.setFont("Helvetica", 6.5)
            c.drawString(x, y - 2.5 * mm, f"{rec['client']} / {rec['farm']}"[:34])
        c.setFont("Helvetica", 8.5)
        c.drawString(x + 34 * mm, y, f"{slug}_Bdy / {slug}_Taipa")
        c.drawRightString(x + 126 * mm, y, area_text)


def _howto(c: canvas.Canvas, job: dict, language: str):
    copy = PDF_COPY[language]
    w, h = PAGE
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColorRGB(0.12, 0.12, 0.10)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(18 * mm, h - 18 * mm, copy["howto"])
    rows = list(job.get("rows") or [])
    first = rows[0] if rows else None
    if first:
        rec, slug, stats = first
        ag_example = f"E:\\AgGPS\\Data\\{rec['client']}\\{rec['farm']}\\{rec['field']}\\Boundary.shp"
        shp_example = f"E:\\Shapefile\\{slug}_Bdy.shp  +  {slug}_Taipa.shp"
        bbox = stats.get("bbox")
        location = ""
        if bbox:
            lat = abs((bbox[1] + bbox[3]) / 2)
            lon = abs((bbox[0] + bbox[2]) / 2)
            location = f" (~{lat:.3f} S, {lon:.3f} W)"
        test_field = f"{rec['field']}{location}"
    else:
        ag_example = "E:\\AgGPS\\Data\\<Grower>\\<Farm>\\<Campo>\\Boundary.shp"
        shp_example = "E:\\Shapefile\\<Campo>_Bdy.shp  +  <Campo>_Taipa.shp"
        test_field = copy["test_field"]

    body = _howto_body(
        language,
        ag_example,
        shp_example,
        test_field,
        artifact_names=job.get("artifact_names"),
    )
    c.setFont("Helvetica", 9.5)
    y = h - 32 * mm
    for line in body:
        for wrapped_line in _wrap_instruction_line(line, w - 36 * mm):
            c.drawString(18 * mm, y, wrapped_line)
            y -= 5.6 * mm
    c.showPage()


def _wrap_instruction_line(
    line: str,
    max_width: float,
    *,
    font_name: str = "Helvetica",
    font_size: float = 9.5,
) -> list[str]:
    if not line or pdfmetrics.stringWidth(line, font_name, font_size) <= max_width:
        return [line]

    wrapped = []
    remaining = line
    continuation = "    "
    while pdfmetrics.stringWidth(remaining, font_name, font_size) > max_width:
        low, high = 1, len(remaining)
        while low < high:
            middle = (low + high + 1) // 2
            if pdfmetrics.stringWidth(remaining[:middle], font_name, font_size) <= max_width:
                low = middle
            else:
                high = middle - 1
        split_at = max(remaining.rfind(char, 0, low + 1) for char in (" ", "\\", "/")) + 1
        if split_at < low // 2:
            split_at = low
        wrapped.append(remaining[:split_at].rstrip())
        remaining = continuation + remaining[split_at:].lstrip()
    wrapped.append(remaining)
    return wrapped


def _howto_body(
    language: str,
    ag_example: str,
    shp_example: str,
    test_field: str,
    *,
    artifact_names: dict[str, str] | None = None,
) -> list[str]:
    artifact_names = artifact_names or {
        "aggps": "AgGPS.zip",
        "shapefile": "Shapefile.zip",
    }
    aggps_zip = artifact_names["aggps"]
    shapefile_zip = artifact_names["shapefile"]
    examples = [f"     AgGPS:     {ag_example}", f"     Shapefile: {shp_example}"]
    bodies = {
        "es": [
            f"ELIJA UN ZIP: descomprima {aggps_zip} o {shapefile_zip}.",
            *examples,
            "Cada ZIP abre en la carpeta lista para copiar. No copie el ZIP cerrado ni mezcle formatos.",
            "",
            "VÍA 1 — RECOMENDADA: use el USB propio del tractor.",
            "1. Apague el tractor y retire su USB. En una computadora, deje .cn1 exactamente como está.",
            "2. NO formatee el USB y NO copie nada dentro de .cn1.",
            "3. Copie AgGPS o Shapefile a la raíz, al lado de .cn1. Devuelva ese mismo USB al tractor.",
            "4. Encienda y espere el mensaje de copia interna. Después abra Data Management → Import2.",
            "5. Un reinicio adicional después de importar puede ser normal.",
            "",
            "VÍA 2 — ALTERNATIVA: segundo pendrive FAT32, 8–32 GB, solo AgGPS o Shapefile.",
            "1. Apague, retire el USB .cn1, coloque el segundo pendrive, encienda y espere la copia.",
            "2. Apague, retire el segundo pendrive, vuelva a colocar el USB .cn1 y encienda.",
            "3. Abra Import2 con el USB .cn1 puesto. Sin .cn1 puede no ver Grower / Farm / Field.",
            "",
            "IMPORT2:",
            "  • AgGPS → Source = Non Pro 700 1     • Shapefile → Source = Shapefile",
            "  • Boundary / *_Bdy → Data Type = Boundary",
            "  • LineFeature / *_Taipa → Guidance / Multiswath / Line",
            f"Primera prueba: importe solo {test_field}.",
            "Auto-select funciona solo dentro del polígono Boundary. Las taipas nunca eligen el campo.",
        ],
        "en": [
            f"CHOOSE ONE ZIP: extract {aggps_zip} or {shapefile_zip}.",
            *examples,
            "Each ZIP opens to the ready-to-copy folder. Do not copy the closed ZIP or mix formats.",
            "",
            "METHOD 1 — RECOMMENDED: use the tractor's own USB.",
            "1. Power off and remove the USB. On a computer, leave .cn1 exactly as it is.",
            "2. DO NOT format the USB and DO NOT copy anything inside .cn1.",
            "3. Copy AgGPS or Shapefile to the root, beside .cn1. Return that same USB to the tractor.",
            "4. Power on and wait for the internal-copy message. Then open Data Management → Import2.",
            "5. One additional restart after importing can be normal.",
            "",
            "METHOD 2 — ALTERNATIVE: second FAT32 drive, 8–32 GB, with only AgGPS or Shapefile.",
            "1. Power off, remove the .cn1 USB, insert the second drive, power on, and wait for copy.",
            "2. Power off, remove the second drive, reinsert the .cn1 USB, and power on.",
            "3. Open Import2 with the .cn1 USB inserted. Without .cn1 it may not show farm entities.",
            "",
            "IMPORT2:",
            "  • AgGPS → Source = Non Pro 700 1     • Shapefile → Source = Shapefile",
            "  • Boundary / *_Bdy → Data Type = Boundary",
            "  • LineFeature / *_Taipa → Guidance / Multiswath / Line",
            f"First test: import only {test_field}.",
            "GPS auto-select works only inside the Boundary polygon. Taipa lines never select a field.",
        ],
        "pt-BR": [
            f"ESCOLHA UM ZIP: descompacte {aggps_zip} ou {shapefile_zip}.",
            *examples,
            "Cada ZIP abre na pasta pronta para copiar. Não copie o ZIP fechado nem misture formatos.",
            "",
            "MÉTODO 1 — RECOMENDADO: use o USB do próprio trator.",
            "1. Desligue e retire o USB. Em um computador, deixe a pasta .cn1 exatamente como está.",
            "2. NÃO formate o USB e NÃO copie nada dentro de .cn1.",
            "3. Copie AgGPS ou Shapefile para a raiz, ao lado de .cn1. Devolva o mesmo USB ao trator.",
            "4. Ligue e aguarde a mensagem de cópia interna. Depois abra Data Management → Import2.",
            "5. Uma reinicialização adicional depois da importação pode ser normal.",
            "",
            "MÉTODO 2 — ALTERNATIVO: segundo pendrive FAT32, 8–32 GB, só AgGPS ou Shapefile.",
            "1. Desligue, retire o USB .cn1, coloque o segundo pendrive, ligue e aguarde a cópia.",
            "2. Desligue, retire o segundo pendrive, recoloque o USB .cn1 e ligue.",
            "3. Abra o Import2 com o USB .cn1. Sem .cn1, as entidades da fazenda podem não aparecer.",
            "",
            "IMPORT2:",
            "  • AgGPS → Source = Non Pro 700 1     • Shapefile → Source = Shapefile",
            "  • Boundary / *_Bdy → Data Type = Boundary",
            "  • LineFeature / *_Taipa → Guidance / Multiswath / Line",
            f"Primeiro teste: importe somente {test_field}.",
            "A seleção por GPS só funciona dentro do Boundary. As taipas nunca selecionam o talhão.",
        ],
    }
    return bodies[language]


def _image_page(
    c: canvas.Canvas,
    img: Path,
    title: str,
    subtitle: str,
    *,
    satellite: bool,
    language: str,
):
    w, h = PAGE
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColorRGB(0.12, 0.12, 0.10)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(12 * mm, h - 10 * mm, title)
    c.setFont("Helvetica", 9)
    c.drawString(12 * mm, h - 16 * mm, subtitle)
    if not satellite:
        _draw_badge(c, w - 48 * mm, h - 19 * mm, PDF_COPY[language]["no_satellite"])
    _draw_img(c, img, 8 * mm, 22 * mm, w - 16 * mm, h - 44 * mm)
    _draw_map_footer(c, language, overview=True)
    c.showPage()


def _field_page(c: canvas.Canvas, page: dict, language: str):
    w, h = PAGE
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    st = page["stats"]
    name = f"{st['client']}  ·  {st['farm']}  ·  {st['field']}"
    c.setFillColorRGB(0.12, 0.12, 0.10)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(12 * mm, h - 11 * mm, name)
    c.setFont("Helvetica", 9)
    c.drawString(12 * mm, h - 17 * mm, field_note(st, language))
    usb = f"USB  {page['slug']}_Bdy  +  {page['slug']}_Taipa"
    c.drawRightString(w - 12 * mm, h - 11 * mm, usb)
    image = page.get("image")
    satellite = bool(page.get("satellite"))
    if not satellite:
        _draw_badge(c, w - 48 * mm, h - 24 * mm, PDF_COPY[language]["no_satellite"])
    if image and Path(image).exists():
        image_path = Path(image)
        ir = ImageReader(str(image_path))
        iw, ih = ir.getSize()
        if iw / ih < 0.82:
            _draw_img(c, image_path, 8 * mm, 23 * mm, 170 * mm, h - 48 * mm)
            _draw_stats_panel(c, st, 188 * mm, h - 42 * mm, language)
        else:
            _draw_img(c, image_path, 8 * mm, 23 * mm, w - 16 * mm, h - 48 * mm)
    _draw_map_footer(c, language)
    c.showPage()


def _draw_img(c: canvas.Canvas, path: Path, x, y, max_w, max_h):
    ir = ImageReader(str(path))
    iw, ih = ir.getSize()
    scale = min(max_w / iw, max_h / ih)
    dw, dh = iw * scale, ih * scale
    c.drawImage(
        ir,
        x + (max_w - dw) / 2,
        y + (max_h - dh) / 2,
        width=dw,
        height=dh,
        preserveAspectRatio=True,
        mask="auto",
    )


def _draw_stats_panel(c: canvas.Canvas, stats: dict, x, y, language: str):
    copy = PDF_COPY[language]
    c.setFillColorRGB(0.12, 0.12, 0.10)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x, y, copy["field_data"])
    rows = [(copy["taipas"], str(stats.get("n_taipas") or 0))]
    if stats.get("area_ha") is not None:
        rows.append((copy["area"], f"{stats['area_ha']:.2f} ha"))
    if stats.get("dz_cm") is not None:
        rows.append((copy["median_dz"], f"{stats['dz_cm']:.1f} cm"))
    if stats.get("zmin") is not None and stats.get("zmax") is not None:
        rows.append((copy["elevations"], f"{stats['zmin']:.1f}–{stats['zmax']:.1f} m"))
    for label, value in rows:
        y -= 12 * mm
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.35, 0.35, 0.32)
        c.drawString(x, y + 4 * mm, label.upper())
        c.setFont("Helvetica-Bold", 14)
        c.setFillColorRGB(0.12, 0.12, 0.10)
        c.drawString(x, y - 2 * mm, value)


def _draw_badge(c: canvas.Canvas, x, y, label: str):
    c.setFillColorRGB(0.94, 0.86, 0.45)
    c.roundRect(x, y, 36 * mm, 8 * mm, 4 * mm, fill=1, stroke=0)
    c.setFillColorRGB(0.12, 0.12, 0.10)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x + 18 * mm, y + 2.5 * mm, label.upper())


def _draw_map_footer(c: canvas.Canvas, language: str, *, overview: bool = False):
    copy = PDF_COPY[language]
    c.setFillColorRGB(0.25, 0.25, 0.25)
    c.setFont("Helvetica", 7.5)
    if overview:
        c.drawString(12 * mm, 11 * mm, copy["overview_footer"])
    else:
        c.drawString(12 * mm, 11 * mm, copy["field_footer"])
    c.drawString(12 * mm, 7 * mm, copy["fixed_geometry"])


def _validate_map_images(job: dict) -> None:
    images = [job.get("overview_image")]
    images.extend(page.get("image") for page in (job.get("field_pages") or []))
    for image_path in images:
        if not image_path:
            continue
        path = Path(image_path)
        if path.stat().st_size > MAX_MAP_BYTES:
            raise ValueError(f"map image exceeds {MAX_MAP_BYTES} bytes: {path.name}")
        with Image.open(path) as image:
            if max(image.size) > MAX_MAP_PX:
                raise ValueError(f"map image exceeds {MAX_MAP_PX}px: {path.name} {image.size}")
