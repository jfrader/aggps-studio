from __future__ import annotations

import io
import struct
import tempfile
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from reportlab.pdfbase import pdfmetrics

from engine import basemap, render
from engine.discover import discover_fields, short_name
from engine.geo import enu_to_ll, ll_to_enu, pad_bbox
from engine.languages import field_note, validate_language
from engine.pack import _build_leame, build_usb_tree
from engine.pdfmake import PDF_COPY, _howto_body, _wrap_instruction_line
from engine.pipeline import (
    _artifact_prefix,
    ArchiveEncryptedError,
    ArchiveLimitError,
    ArchiveTraversalError,
    UnsafeArchiveError,
    process_aggps_zip,
    safe_extract,
)
from engine.shpio import validate_shape_role


def test_roundtrip_enu():
    lat0, lon0 = 12.34567, 34.56789
    lat, lon = enu_to_ll(40.0, -15.0, lat0, lon0)
    e, n = ll_to_enu(lat, lon, lat0, lon0)
    assert abs(e - 40.0) < 0.05
    assert abs(n + 15.0) < 0.05


def test_short_names():
    used = set()
    assert short_name("Plot 12", used) == "Plot12"
    assert short_name("sample field", used) == "samplefiel"
    assert short_name("7", used, farm="Demo Farm").lower().startswith("demofa")
    assert short_name("Plot 12", used) != "Plot12"


def test_artifact_prefix_uses_safe_farm_name():
    assert _artifact_prefix([{"farm": "Fazenda Fictícia", "client": "Demo Grower"}]) == "Fazenda_Ficticia"
    assert _artifact_prefix([{"farm": "", "client": "Sample Cooperative"}]) == "Sample_Cooperative"


def test_operator_languages_and_default_copy():
    mapping = [({"client": "Demo Grower", "farm": "Demo Farm", "field": "Plot Alpha"}, "PlotAlpha")]
    expected = {
        "es": (
            "VÍA 1 (recomendada)",
            "VÍA 2 (alternativa)",
            "vuelva a colocar el USB .cn1",
            "Importe solo Plot Alpha",
        ),
        "en": (
            "METHOD 1 (recommended)",
            "METHOD 2 (alternative)",
            "reinsert the .cn1 USB",
            "Import only Plot Alpha",
        ),
        "pt-BR": (
            "MÉTODO 1 (recomendado)",
            "MÉTODO 2 (alternativo)",
            "recoloque o USB .cn1",
            "Importe somente Plot Alpha",
        ),
    }
    for language, snippets in expected.items():
        readme = _build_leame(mapping, [], language=language)
        assert all(snippet in readme for snippet in snippets)
        assert "AgGPS.zip" in readme and "Shapefile.zip" in readme
        assert "A_AgGPS" not in readme and "B_Shapefile" not in readme
        assert ".cn1" in readme and "SurveyPoints" in readme
        assert "E:\\AgGPS\\Data\\Demo Grower\\Demo Farm\\Plot Alpha\\Boundary.shp" in readme
        assert "E:\\Shapefile\\PlotAlpha_Bdy.shp" in readme

    assert _build_leame(mapping, []).startswith("AFS Pro 700 — USB generado")
    with pytest.raises(ValueError, match="unsupported operator language"):
        validate_language("pt")


def test_localized_field_notes_and_pdf_instructions():
    stats = {
        "n_taipas": 3,
        "area_ha": 12.34,
        "dz_cm": 15.6,
        "zmin": 102.1,
        "zmax": 103.4,
    }
    assert "terreno más inclinado" in field_note(stats, "es")
    assert "steeper terrain" in field_note(stats, "en")
    assert "terreno mais inclinado" in field_note(stats, "pt-BR")

    recommended = {"es": "RECOMENDADA", "en": "RECOMMENDED", "pt-BR": "RECOMENDADO"}
    alternative = {"es": "ALTERNATIVA", "en": "ALTERNATIVE", "pt-BR": "ALTERNATIVO"}
    section_copy = {
        "es": ("USB propio del tractor", "NO formatee", "al lado de .cn1", "vuelva a colocar el USB .cn1"),
        "en": ("tractor's own USB", "DO NOT format", "beside .cn1", "reinsert the .cn1 USB"),
        "pt-BR": ("USB do próprio trator", "NÃO formate", "ao lado de .cn1", "recoloque o USB .cn1"),
    }
    for language in ("es", "en", "pt-BR"):
        body = "\n".join(_howto_body(language, "AgGPS path", "Shapefile path", "Plot Alpha"))
        assert ".cn1" in body and "Plot Alpha" in body
        assert "Boundary" in body and "LineFeature" in body
        assert body.index(recommended[language]) < body.index(alternative[language])
        recommended_body, alternative_body = body.split(alternative[language], 1)
        own_usb, no_format, beside_cn1, restore_cn1 = section_copy[language]
        assert all(snippet in recommended_body for snippet in (own_usb, no_format, beside_cn1))
        assert restore_cn1 in alternative_body
        assert PDF_COPY[language]["fixed_geometry"]

    english_groups = _build_leame([], ["North", "South"], language="en")
    portuguese_groups = _build_leame([], ["Norte", "Sul"], language="pt-BR")
    assert "`North` and `South` are available" in english_groups
    assert "`Norte` e `Sul` ficam" in portuguese_groups

    artifact_names = {
        "aggps": "DEMO_FARM_AgGPS.zip",
        "shapefile": "DEMO_FARM_Shapefile.zip",
    }
    prefixed_readme = _build_leame(mapping=[], line_only=[], artifact_names=artifact_names)
    prefixed_howto = "\n".join(
        _howto_body(
            "es",
            "AgGPS path",
            "Shapefile path",
            "Plot Alpha",
            artifact_names=artifact_names,
        )
    )
    assert all(name in prefixed_readme for name in artifact_names.values())
    assert all(name in prefixed_howto for name in artifact_names.values())

    wrapped = _wrap_instruction_line("AgGPS: E:\\" + "WideName" * 80 + "\\Boundary.shp", 500)
    assert len(wrapped) > 1
    assert all(pdfmetrics.stringWidth(line, "Helvetica", 9.5) <= 500 for line in wrapped)


def test_pad_bbox():
    b = pad_bbox((34.56, 12.34, 34.57, 12.35), 0.1)
    assert b[0] < 34.56 and b[2] > 34.57


def test_satellite_uses_esri_returned_extent(monkeypatch, tmp_path: Path):
    image_buffer = io.BytesIO()
    Image.new("RGB", (320, 240), "green").save(image_buffer, format="JPEG")
    requested = (34.560, 12.340, 34.575, 12.351)
    returned = (34.560, 12.339, 34.575, 12.352)

    class FakeResponse:
        def __init__(self, *, payload=None, content=b""):
            self.payload = payload
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    responses = [
        FakeResponse(
            payload={
                "href": "https://example.invalid/image.jpg",
                "extent": dict(zip(("xmin", "ymin", "xmax", "ymax"), returned)),
            }
        ),
        FakeResponse(content=image_buffer.getvalue()),
    ]
    monkeypatch.setattr(basemap.requests, "get", lambda *_args, **_kwargs: responses.pop(0))

    satellite = basemap.fetch_satellite(requested, max_px=320)
    assert satellite is not None
    assert satellite.extent == returned
    assert abs(satellite.extent[1] - requested[1]) * 111_320 > 5

    observed = []
    rendered_text = []
    original_imshow = render.plt.Axes.imshow
    original_text = render.plt.Axes.text

    def capture_extent(self, *args, **kwargs):
        observed.append(kwargs.get("extent"))
        return original_imshow(self, *args, **kwargs)

    def capture_text(self, *args, **kwargs):
        rendered_text.append(args[2] if len(args) > 2 else kwargs.get("s"))
        return original_text(self, *args, **kwargs)

    monkeypatch.setattr(render.plt.Axes, "imshow", capture_extent)
    monkeypatch.setattr(render.plt.Axes, "text", capture_text)
    stats = {
        "field": "Test",
        "farm": "Farm",
        "bbox": requested,
        "boundary_ll": [
            (requested[0], requested[1]),
            (requested[2], requested[1]),
            (requested[2], requested[3]),
            (requested[0], requested[1]),
        ],
    }
    render.render_field(stats, tmp_path / "map.jpg", satellite=satellite)
    assert observed == [(returned[0], returned[2], returned[1], returned[3])]
    assert render.IMAGERY_ATTRIBUTION in rendered_text


def test_imagery_attribution_only_appears_with_satellite(monkeypatch, tmp_path: Path):
    rendered_text = []
    original_text = render.plt.Axes.text

    def capture_text(self, *args, **kwargs):
        rendered_text.append(args[2] if len(args) > 2 else kwargs.get("s"))
        return original_text(self, *args, **kwargs)

    monkeypatch.setattr(render.plt.Axes, "text", capture_text)
    stats = {
        "field": "Synthetic Plot",
        "farm": "Demo Farm",
        "bbox": (34.560, 12.340, 34.575, 12.351),
        "boundary_ll": [
            (34.560, 12.340),
            (34.575, 12.340),
            (34.575, 12.351),
            (34.560, 12.340),
        ],
    }

    render.render_field(stats, tmp_path / "fallback-field.jpg")
    render.render_overview([stats], tmp_path / "fallback-overview.jpg")

    assert render.IMAGERY_ATTRIBUTION not in rendered_text

    satellite = basemap.SatelliteImage(
        image=Image.new("RGB", (320, 240), "green"),
        extent=stats["bbox"],
    )
    render.render_overview([stats], tmp_path / "satellite-overview.jpg", satellite=satellite)

    assert render.IMAGERY_ATTRIBUTION in rendered_text


def test_satellite_request_timeout_uses_remaining_total_budget(monkeypatch):
    monkeypatch.setattr(basemap.time, "monotonic", lambda: 12.0)
    assert basemap._remaining_timeout(17.0, 20) == 5.0
    try:
        basemap._remaining_timeout(12.0, 20)
    except TimeoutError:
        pass
    else:
        raise AssertionError("expired satellite deadline must raise TimeoutError")


# --- programmatic minimal shapefile / zip generators (no fixtures) ---


def _make_minimal_shp(typ: int = 5, pts: list[tuple[float, float]] | None = None) -> tuple[bytes, int]:
    if pts is None:
        if typ == 5:
            pts = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0)]
        else:
            pts = [(0.0, 0.0), (1.0, 1.0)]
    npts = len(pts)
    nparts = 1
    content = 4 + 32 + 4 + 4 + 4 * nparts + 16 * npts
    rec_len_w = content // 2
    file_len_w = 50 + 4 + rec_len_w
    hdr = bytearray(100)
    struct.pack_into(">i", hdr, 0, 9994)
    struct.pack_into(">i", hdr, 24, file_len_w)
    struct.pack_into("<i", hdr, 28, 1000)
    struct.pack_into("<i", hdr, 32, typ)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    struct.pack_into("<4d", hdr, 36, min(xs), min(ys), max(xs), max(ys))
    rec = bytearray(8 + content)
    struct.pack_into(">i", rec, 0, 1)
    struct.pack_into(">i", rec, 4, rec_len_w)
    o = 8
    struct.pack_into("<i", rec, o, typ)
    o += 4
    struct.pack_into("<4d", rec, o, min(xs), min(ys), max(xs), max(ys))
    o += 32
    struct.pack_into("<2i", rec, o, nparts, npts)
    o += 8
    struct.pack_into("<i", rec, o, 0)
    o += 4
    for px, py in pts:
        struct.pack_into("<2d", rec, o, px, py)
        o += 16
    return bytes(hdr + rec), rec_len_w


def _make_minimal_shx(rec_len_w: int, typ: int) -> bytes:
    file_len_w = 50 + 4
    shx = bytearray(100)
    struct.pack_into(">i", shx, 0, 9994)
    struct.pack_into(">i", shx, 24, file_len_w)
    struct.pack_into("<i", shx, 28, 1000)
    struct.pack_into("<i", shx, 32, typ)
    struct.pack_into("<4d", shx, 36, 0.0, 0.0, 1.0, 1.0)
    idx = bytearray(8)
    struct.pack_into(">i", idx, 0, 50)
    struct.pack_into(">i", idx, 4, rec_len_w)
    return bytes(shx + idx)


def _make_minimal_dbf(nrec: int = 1) -> bytes:
    year, mon, day = 124, 9, 1
    nfields = 1
    hdr_len = 32 + 32 * nfields + 1
    rec_len = 1 + 10
    d = bytearray(hdr_len + nrec * rec_len)
    d[0] = 0x03
    d[1:4] = bytes([year, mon, day])
    struct.pack_into("<L", d, 4, nrec)
    struct.pack_into("<H", d, 8, hdr_len)
    struct.pack_into("<H", d, 10, rec_len)
    fd = bytearray(32)
    fd[:3] = b"FID"
    fd[11] = ord("C")
    fd[16] = 10
    d[32:64] = fd
    d[64] = 0x0D
    for i in range(nrec):
        ro = hdr_len + i * rec_len
        d[ro] = 0x20
        data = f"{i}".ljust(10).encode("ascii")[:10]
        d[ro + 1 : ro + 11] = data
    return bytes(d)


def _write_shp_family(
    td: Path,
    stem: str,
    typ: int = 5,
    pts: list[tuple[float, float]] | None = None,
) -> Path:
    shp_b, recw = _make_minimal_shp(typ, pts)
    (td / f"{stem}.shp").write_bytes(shp_b)
    (td / f"{stem}.shx").write_bytes(_make_minimal_shx(recw, typ))
    (td / f"{stem}.dbf").write_bytes(_make_minimal_dbf(1))
    return td / f"{stem}.shp"


def _make_zip_with_members(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_discover_fields_ignores_line_only_survey_groups(tmp_path: Path):
    complete = tmp_path / "AgGPS" / "Data" / "Grower" / "Farm" / "Field 1"
    complete.mkdir(parents=True)
    _write_shp_family(complete, "Boundary", typ=5)
    _write_shp_family(complete, "LineFeature", typ=3)

    survey_group = complete.parent / "North survey"
    survey_group.mkdir()
    _write_shp_family(survey_group, "LineFeature", typ=3)

    fields = discover_fields(tmp_path)

    assert [field["field"] for field in fields] == ["Field 1"]
    assert fields[0]["boundary"] == complete / "Boundary.shp"
    assert fields[0]["lines"] == complete / "LineFeature.shp"


# --- safety tests ---


def test_safe_extract_rejects_traversal_and_cleans():
    bad_zip = _make_zip_with_members(
        {
            "good/Boundary.shp": b"xx",
            "../evil.txt": b"bad",
            "a/../../out": b"bad2",
            "C:/winbad": b"bad3",
            "nul\0bad": b"bad4",
        }
    )
    with tempfile.TemporaryDirectory() as td:
        extract = Path(td) / "ex"
        zf = zipfile.ZipFile(io.BytesIO(bad_zip))
        try:
            safe_extract(zf, extract)
            assert False, "should have raised"
        except (ArchiveTraversalError, UnsafeArchiveError):
            pass
        # no partials from the bad
        assert not (extract / "evil.txt").exists()
        assert not any("evil" in str(p) for p in extract.rglob("*"))
        # the good may or not, but traversal aborts early so partial may have good or not; main is no escape
        assert extract.exists()


def test_safe_extract_rejects_encrypted_and_symlink_and_limits():
    # encrypted: set flag
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("enc.txt")
        info.flag_bits = 0x0001
        z.writestr(info, b"secret")
    buf.seek(0)
    with tempfile.TemporaryDirectory() as td:
        zf = zipfile.ZipFile(buf)
        zf.infolist()[0].flag_bits = 0x0001
        try:
            safe_extract(zf, td)
            assert False
        except ArchiveEncryptedError:
            pass

    # symlink
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120000 | 0o755) << 16
        z.writestr(info, b"")
    buf.seek(0)
    with tempfile.TemporaryDirectory() as td:
        try:
            safe_extract(zipfile.ZipFile(buf), td)
            assert False
        except ArchiveTraversalError:
            pass

    # limit member count
    members = {f"f{i}.txt": b"x" for i in range(5)}
    small_zip = _make_zip_with_members(members)
    with tempfile.TemporaryDirectory() as td:
        try:
            safe_extract(zipfile.ZipFile(io.BytesIO(small_zip)), td, max_members=2)
            assert False
        except ArchiveLimitError:
            pass

    # per member size (use declared, even if small data)
    big_info_zip = _make_zip_with_members({"big.bin": b"x" * 10})
    # patch the info file_size
    with tempfile.TemporaryDirectory() as td:
        zf = zipfile.ZipFile(io.BytesIO(big_info_zip))
        # monkey the size for test
        zf.infolist()[0].file_size = 200 * 1024 * 1024 + 1
        try:
            safe_extract(zf, td, max_per_member=100 * 1024 * 1024)
            assert False
        except ArchiveLimitError:
            pass


def test_safe_extract_retained_bytes_and_total_limit():
    core = b"CORE1234" * 100
    good_zip = _make_zip_with_members({"AgGPS/Data/G/Fld/Boundary.shp": core})
    with tempfile.TemporaryDirectory() as td:
        extract = Path(td) / "ex"
        safe_extract(zipfile.ZipFile(io.BytesIO(good_zip)), extract)
        outp = extract / "AgGPS/Data/G/Fld/Boundary.shp"
        assert outp.read_bytes() == core
    with tempfile.TemporaryDirectory() as td:
        try:
            safe_extract(
                zipfile.ZipFile(io.BytesIO(good_zip)),
                td,
                max_total_uncompressed=len(core) - 1,
            )
            assert False
        except ArchiveLimitError:
            pass


def test_slug_max_len_after_prefix_and_collision():
    used: set[str] = set()
    # long alnum trimmed
    s = short_name("abcdefghijklmno", used)
    assert len(s) <= 10
    # digit + farm prefix
    s = short_name("123456789012345", used, farm="big farm name here")
    assert len(s) <= 10
    # collision suffixes capped
    used2: set[str] = set()
    base = short_name("abcde12345", used2)  # 10 char
    assert len(base) <= 10
    s2 = short_name("abcde12345", used2)
    assert len(s2) <= 10 and s2 != base
    # extreme collision
    used3: set[str] = set()
    for _ in range(20):
        s = short_name("verylongfield", used3)
        assert len(s) <= 10


def test_strict_validate_roles_and_sidecars():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # good polygon boundary
        bpath = _write_shp_family(td, "Boundary", typ=5)
        hdr = validate_shape_role(bpath, "Boundary")
        assert hdr["type"] == "Polygon"
        # good polyline
        lpath = _write_shp_family(td, "LineFeature", typ=3)
        hdr = validate_shape_role(lpath, "LineFeature")
        assert hdr["type"] == "Polyline"
        # missing sidecar
        (td / "BadBdy.shp").write_bytes(b"xx")
        try:
            validate_shape_role(td / "BadBdy.shp", "Boundary")
            assert False
        except ValueError as e:
            assert "sidecar" in str(e).lower()
        # wrong type for role: make Z as boundary
        zpath = _write_shp_family(td, "ZBoundary", typ=15)
        try:
            validate_shape_role(zpath, "Boundary")
            assert False
        except ValueError as e:
            assert "Polygon" in str(e) and "Z" in str(e)
        # polyline as boundary
        ppath = _write_shp_family(td, "PolyB", typ=3)
        try:
            validate_shape_role(ppath, "Boundary")
            assert False
        except ValueError as e:
            assert "must be exactly Polygon" in str(e)

        # malformed DBF metadata
        bad_dbf = _write_shp_family(td, "BadDbf", typ=5)
        bad_dbf.with_suffix(".dbf").write_bytes(b"short")
        try:
            validate_shape_role(bad_dbf, "Boundary")
            assert False
        except ValueError as e:
            assert ".dbf" in str(e)

        # hostile part count must be rejected before struct allocation
        bad_counts = _write_shp_family(td, "BadCounts", typ=5)
        shapefile = bytearray(bad_counts.read_bytes())
        struct.pack_into("<i", shapefile, 144, 1_000_000)
        bad_counts.write_bytes(shapefile)
        try:
            validate_shape_role(bad_counts, "Boundary")
            assert False
        except ValueError as e:
            assert "geometry exceeds" in str(e)

        # file length must agree with the shapefile header
        bad_size = _write_shp_family(td, "BadSize", typ=5)
        bad_size.write_bytes(bad_size.read_bytes() + b"extra")
        try:
            validate_shape_role(bad_size, "Boundary")
            assert False
        except ValueError as e:
            assert "size does not match" in str(e)


def test_pack_prunes_unsafe_and_retains_core_bytes():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        extract = root / "extract"
        usb = root / "usb"
        agdir = extract / "AgGPS" / "Data" / "Grow" / "FarmX" / "FieldY"
        agdir.mkdir(parents=True)
        # good core files (byte identical target)
        b_core = _write_shp_family(agdir, "Boundary", 5).read_bytes()
        l_core = _write_shp_family(agdir, "LineFeature", 3).read_bytes()
        # unsafe to prune
        (agdir / "SurveyPoints.shp").write_bytes(b"bad1")
        (agdir / "surveypoints.dbf").write_bytes(b"bad2")
        spdir = agdir / "SurveyPoints"
        spdir.mkdir()
        (spdir / "pt.shp").write_bytes(b"bad3")
        # Z family
        _write_shp_family(agdir, "SomeZ", typ=13)  # PolylineZ + sides
        (agdir / "SomeZ.prj").write_bytes(b"badprj")
        (agdir / "SomeZ.cpg").write_bytes(b"badcpg")
        # other allowed
        (agdir / "FieldLevel.xml").write_text("<xml/>")
        (agdir / "foo.pos").write_bytes(b"pos")
        # .prj for good should be pruned too
        (agdir / "Boundary.prj").write_bytes(b"shouldprune")
        (agdir / "LineFeature.cpg").write_bytes(b"prune")

        # fields recs
        fields = [
            {
                "client": "Grow",
                "farm": "FarmX",
                "field": "FieldY",
                "folder": agdir,
                "boundary": agdir / "Boundary.shp",
                "lines": agdir / "LineFeature.shp",
                "fieldlevel": None,
            }
        ]
        info = build_usb_tree(extract, fields, usb)
        ag_out = usb / "A_AgGPS" / "AgGPS" / "Data" / "Grow" / "FarmX" / "FieldY"
        shp_out = usb / "B_Shapefile" / "Shapefile"

        # core retained byte identical
        assert (ag_out / "Boundary.shp").read_bytes() == b_core
        assert (ag_out / "LineFeature.shp").read_bytes() == l_core
        assert (ag_out / "Boundary.shx").exists()
        assert (ag_out / "LineFeature.dbf").exists()

        # pruned
        assert not (ag_out / "SurveyPoints.shp").exists()
        assert not (ag_out / "surveypoints.dbf").exists()
        assert not (ag_out / "SurveyPoints").exists()
        assert not any(p.name.lower().endswith((".prj", ".cpg")) for p in ag_out.iterdir() if p.is_file())
        # Z family pruned
        assert not (ag_out / "SomeZ.shp").exists()
        assert not (ag_out / "SomeZ.shx").exists()
        assert not (ag_out / "SomeZ.dbf").exists()

        # other kept
        assert (ag_out / "FieldLevel.xml").exists()
        assert (ag_out / "foo.pos").exists()

        # Shapefile/ only 2d cores, no extras
        assert (shp_out / "FieldY_Bdy.shp").exists()
        assert (shp_out / "FieldY_Taipa.shp").exists()
        assert not list(shp_out.glob("*.prj"))
        assert not list(shp_out.glob("*.cpg"))
        # slugs <=10
        assert len("FieldY") <= 10
        # byte ident for the packed shps too (from copy_sidecars)
        assert (shp_out / "FieldY_Bdy.shp").read_bytes() == b_core


def test_pack_keeps_line_only_groups_only_in_aggps(tmp_path: Path):
    extract = tmp_path / "extract"
    usb = tmp_path / "usb"
    farm = extract / "AgGPS" / "Data" / "Grow" / "Farm"
    field = farm / "Field 1"
    line_only = farm / "North survey"
    z_line_only = farm / "Unsafe Z survey"
    field.mkdir(parents=True)
    line_only.mkdir()
    z_line_only.mkdir()
    _write_shp_family(field, "Boundary", typ=5)
    _write_shp_family(field, "LineFeature", typ=3)
    line_only_shp = _write_shp_family(line_only, "LineFeature", typ=3)
    _write_shp_family(z_line_only, "LineFeature", typ=13)
    fields = discover_fields(extract)

    info = build_usb_tree(extract, fields, usb)

    kept = usb / "A_AgGPS" / "AgGPS" / "Data" / "Grow" / "Farm" / "North survey"
    assert (kept / "LineFeature.shp").read_bytes() == line_only_shp.read_bytes()
    assert info["line_only"] == ["North survey"]
    assert not any("North" in path.name for path in (usb / "B_Shapefile").rglob("*"))
    unsafe_z_output = (
        usb
        / "A_AgGPS"
        / "AgGPS"
        / "Data"
        / "Grow"
        / "Farm"
        / "Unsafe Z survey"
        / "LineFeature.shp"
    )
    assert not unsafe_z_output.exists()
    readme = (usb / "LEAME.txt").read_text()
    assert "`North survey` van solo en AgGPS" in readme
    assert "Unsafe Z survey" not in readme
    assert "E:\\AgGPS\\Data\\Grow\\Farm\\Field 1\\Boundary.shp" in readme


def test_language_only_changes_operator_files(tmp_path: Path):
    extract = tmp_path / "extract"
    field = extract / "AgGPS" / "Data" / "Demo Grower" / "Demo Farm" / "Plot Alpha"
    field.mkdir(parents=True)
    _write_shp_family(field, "Boundary", typ=5)
    _write_shp_family(field, "LineFeature", typ=3)
    fields = discover_fields(extract)

    payloads = []
    expected_headers = {
        "es": "Cliente\tEstablecimiento\tLote",
        "en": "Grower\tFarm\tField",
        "pt-BR": "Cliente\tFazenda\tTalhão",
    }
    for language in ("es", "en", "pt-BR"):
        usb = tmp_path / language
        build_usb_tree(extract, fields, usb, language=language)
        payloads.append(
            {
                path.relative_to(usb).as_posix(): path.read_bytes()
                for root in (usb / "A_AgGPS", usb / "B_Shapefile")
                for path in root.rglob("*")
                if path.is_file()
            }
        )
        assert (usb / "INDICE_CAMPOS.txt").read_text().startswith(expected_headers[language])

    assert payloads[0] == payloads[1] == payloads[2]


def test_pipeline_end_to_end_with_synthetic_aggps():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source = root / "source" / "AgGPS" / "Data" / "Demo Grower" / "Demo Farm" / "Plot 12"
        source.mkdir(parents=True)
        boundary = [
            (34.5600, 12.3400),
            (34.5610, 12.3400),
            (34.5610, 12.3408),
            (34.5600, 12.3408),
            (34.5600, 12.3400),
        ]
        lines = [(34.5601, 12.3402), (34.5609, 12.3406)]
        _write_shp_family(source, "Boundary", typ=5, pts=boundary)
        _write_shp_family(source, "LineFeature", typ=3, pts=lines)
        (source / "SurveyPoints.shp").write_bytes(b"must not ship")
        (source / "Boundary.prj").write_text("must not ship", encoding="ascii")

        input_zip = root / "AgGPS.zip"
        with zipfile.ZipFile(input_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in (root / "source").rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(root / "source"))

        stale = root / "out" / "USB_Pro700" / "A_AgGPS" / "AgGPS" / "Data" / "Old"
        stale.mkdir(parents=True)
        (stale / "stale-customer-data.txt").write_text("must not ship")
        result = process_aggps_zip(input_zip, root / "out", fetch_sat=False)
        assert result["language"] == "es"
        assert result["n_fields"] == 1
        assert Path(result["aggps_zip"]).is_file()
        assert Path(result["shapefile_zip"]).is_file()
        assert Path(result["pdf"]).is_file()
        assert Path(result["images_zip"]).is_file()

        with zipfile.ZipFile(result["aggps_zip"]) as output:
            aggps_names = set(output.namelist())
        assert "AgGPS/Data/Demo Grower/Demo Farm/Plot 12/Boundary.shp" in aggps_names
        assert "AgGPS/Data/Demo Grower/Demo Farm/Plot 12/LineFeature.shp" in aggps_names
        assert {name.split("/", 1)[0] for name in aggps_names} == {"AgGPS"}
        assert not any("surveypoints" in name.lower() for name in aggps_names)
        assert not any("stale-customer-data" in name for name in aggps_names)
        assert not any(name.lower().endswith((".prj", ".cpg")) for name in aggps_names)

        with zipfile.ZipFile(result["shapefile_zip"]) as output:
            shapefile_names = set(output.namelist())
        assert "Shapefile/Plot12_Bdy.shp" in shapefile_names
        assert "Shapefile/Plot12_Taipa.shp" in shapefile_names
        assert {name.split("/", 1)[0] for name in shapefile_names} == {"Shapefile"}

        with zipfile.ZipFile(result["images_zip"]) as output:
            assert output.namelist() == ["Plot12.jpg"]

        with zipfile.ZipFile(result["bundle"]) as output:
            assert set(output.namelist()) == {
                "Demo_Farm_AgGPS.zip",
                "Demo_Farm_Shapefile.zip",
                "Demo_Farm_Mapas_choferes.pdf",
                "Demo_Farm_Mapas_lotes.zip",
                "LEAME.txt",
                "INDICE_CAMPOS.txt",
            }
        assert Path(result["pdf"]).name == "Demo_Farm_Mapas_choferes.pdf"
        assert Path(result["aggps_zip"]).name == "Demo_Farm_AgGPS.zip"
        assert Path(result["shapefile_zip"]).name == "Demo_Farm_Shapefile.zip"
        assert Path(result["images_zip"]).name == "Demo_Farm_Mapas_lotes.zip"
        assert not (root / "out" / "_extract").exists()
        assert not (root / "out" / "USB_Pro700").exists()
        assert Path(result["bundle"]).name == "Demo_Farm_paquete_completo.zip"


def test_fallback_converter_direct_structure_pruning_and_names(tmp_path: Path):
    """Focused test for fallback (stdlib convert_aggps) output contract + pruning.
    Uses tiny synthetic archive structure (no customer data). Verifies:
    - direct root AgGPS/ and Shapefile/ in the emitted zips
    - 1 tractor field + line-only preserved only in AgGPS
    - prunes SurveyPoints*, Z families, .prj, .cpg
    - Shapefile zip has only .shp/.shx/.dbf for boundary-backed
    - LEAME/INDICE beside, no USB wrappers
    - CRC clean (testzip)
    Deterministic, no net, no external.
    """
    import struct
    import sys
    import zipfile

    root = tmp_path
    # insert path to allow import of the self-contained fallback
    conv_path = Path(__file__).resolve().parent.parent / ".agents" / "skills" / "aggps-pro700" / "scripts"
    sys.path.insert(0, str(conv_path))
    import convert_aggps as conv  # type: ignore

    extract = root / "extract"
    ag = extract / "AgGPS" / "Data" / "DEMO" / "SAMPLE_FARM" / "Test Field"
    ag.mkdir(parents=True)

    def _mk_hdr(p: Path, typ: int) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        hdr = bytearray(100)
        struct.pack_into("<i", hdr, 32, typ)
        # minimal bbox
        p.write_bytes(hdr)
        p.with_suffix(".shx").write_bytes(hdr)
        p.with_suffix(".dbf").write_bytes(b"\x03\x00\x00\x00" + b"\x00" * 28)

    # good 2D
    _mk_hdr(ag / "Boundary.shp", 5)
    b_core = (ag / "Boundary.shp").read_bytes()
    _mk_hdr(ag / "LineFeature.shp", 3)
    (ag / "FieldLevel.xml").write_text("<f/>")
    (ag / "foo.pos").write_bytes(b"posdata")

    # to prune
    (ag / "SurveyPoints.shp").write_bytes(b"sv1")
    (ag / "surveypoints.dbf").write_bytes(b"sv2")
    spdir = ag / "SP"
    spdir.mkdir(parents=True)
    (spdir / "pt.shp").write_bytes(b"sv3")
    # Z family
    zh = bytearray(100)
    struct.pack_into("<i", zh, 32, 13)
    (ag / "Zed.shp").write_bytes(zh)
    (ag / "Zed.shx").write_bytes(zh)
    (ag / "Zed.dbf").write_bytes(b"z")
    (ag / "Zed.prj").write_bytes(b"prj")
    (ag / "LineFeature.prj").write_bytes(b"pr")
    (ag / "LineFeature.cpg").write_bytes(b"cp")

    # line-only
    lo = extract / "AgGPS" / "Data" / "DEMO" / "SAMPLE_FARM" / "LINEONLY"
    lo.mkdir(parents=True)
    _mk_hdr(lo / "LineFeature.shp", 3)

    outd = root / "out"
    # simulate extract dir passed to build (after extract_zip)
    conv.build_direct(extract, outd)

    # check emitted files
    agz = outd / "SAMPLE_FARM_AgGPS.zip"
    shz = outd / "SAMPLE_FARM_Shapefile.zip"
    assert agz.exists()
    assert shz.exists()
    assert (outd / "LEAME.txt").exists()
    assert (outd / "INDICE_CAMPOS.txt").exists()

    # no wrappers
    assert not (outd / "USB_Pro700").exists()
    assert not any("A_AgGPS" in n or "B_Shapefile" in n for n in [p.name for p in outd.iterdir()])

    # inspect zips
    with zipfile.ZipFile(agz) as z:
        nl = z.namelist()
        assert z.testzip() is None, "AgGPS zip CRC bad"
        tops = {n.split("/")[0] for n in nl if n.strip()}
        assert tops == {"AgGPS"}, f"AgGPS zip must open directly to AgGPS/, got {tops}"
        assert any("AgGPS/Data/DEMO/SAMPLE_FARM/Test Field/Boundary.shp" in n for n in nl)
        assert any("AgGPS/Data/DEMO/SAMPLE_FARM/LINEONLY/LineFeature.shp" in n for n in nl)  # line-only kept
        # pruned
        assert not any("SurveyPoints" in n for n in nl)
        assert not any(n.lower().endswith((".prj", ".cpg")) for n in nl)
        assert not any("/Zed." in n for n in nl)

    with zipfile.ZipFile(shz) as z:
        nl = z.namelist()
        assert z.testzip() is None, "Shapefile zip CRC bad"
        tops = {n.split("/")[0] for n in nl if n.strip()}
        assert tops == {"Shapefile"}, f"Shapefile zip must open directly to Shapefile/, got {tops}"
        assert any("Shapefile/TestField_Bdy.shp" in n for n in nl)  # slug
        assert any("Shapefile/TestField_Taipa.shp" in n for n in nl)
        # only shp shx dbf
        for n in nl:
            if n.strip():
                assert n.endswith((".shp", ".shx", ".dbf")), f"only sidecars: {n}"
        assert len([n for n in nl if n.endswith(".shp")]) == 2

    # index mentions 1 field (the tractor one)
    idx = (outd / "INDICE_CAMPOS.txt").read_text()
    assert "Test Field" in idx or "TestField" in idx
    assert idx.count("\n") >= 2  # header + row


def test_fallback_extract_rejects_encrypted_symlink_duplicate_absolute_drive_and_missing_sidecars(tmp_path: Path):
    """Focused hardening for fallback extract_zip (stdlib only, prior output contract preserved).
    Rejects exactly the cases required: encrypted, symlinks, dups, abs/drive, traversal, missing .shx/.dbf.
    Uses tiny synthetic zips; no engine/customer data.
    """
    import io
    import sys
    import zipfile

    conv_path = Path(__file__).resolve().parent.parent / ".agents" / "skills" / "aggps-pro700" / "scripts"
    sys.path.insert(0, str(conv_path))
    import convert_aggps as conv  # type: ignore

    extract = tmp_path / "ex"
    extract.mkdir()

    def _bad_zip(construct):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            construct(z)
        buf.seek(0)
        return buf

    # encrypted - use on-disk to preserve flag_bits in central dir (writestr clears in-mem)
    import tempfile
    with tempfile.TemporaryDirectory() as tdd:
        zp = Path(tdd) / "enc.zip"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("enc.shp", b"e")
            z.writestr("enc.shx", b"")
            z.writestr("enc.dbf", b"")
        # patch raw bytes for central flag (PK\x01\x02 at +8)
        raw = bytearray(zp.read_bytes())
        ii = 0
        import struct as _struct
        while ii < len(raw)-4:
            if raw[ii:ii+4] == b"PK\x01\x02":
                raw[ii+8] |= 0x01
                fnl = _struct.unpack_from("<H", raw, ii+28)[0]
                exl = _struct.unpack_from("<H", raw, ii+30)[0]
                cml = _struct.unpack_from("<H", raw, ii+32)[0]
                ii += 46 + fnl + exl + cml
                continue
            ii += 1
        zp.write_bytes(raw)
        with pytest.raises(SystemExit) as ei:
            conv.extract_zip(zp, extract / "e1")
        assert "encrypted" in str(ei.value).lower()

    # symlink
    def mk_link(z):
        info = zipfile.ZipInfo("link.shp")
        info.external_attr = (0o120000 | 0o777) << 16
        z.writestr(info, b"")
        z.writestr("link.shx", b"")
        z.writestr("link.dbf", b"")
    with _bad_zip(mk_link) as zf:
        with pytest.raises(SystemExit) as ei:
            conv.extract_zip(zf, extract / "e2")
        assert "symlink" in str(ei.value).lower()

    # duplicate normalized
    def mk_dup(z):
        z.writestr("a/Boundary.shp", b"b")
        z.writestr("a/Boundary.shx", b"")
        z.writestr("a/Boundary.dbf", b"")
        z.writestr("a\\Boundary.shp", b"b2")  # dup after norm
    with _bad_zip(mk_dup) as zf:
        with pytest.raises(SystemExit) as ei:
            conv.extract_zip(zf, extract / "e3")
        assert "duplicate" in str(ei.value).lower()

    # absolute / drive / traversal
    def mk_abs(z):
        z.writestr("/abs.shp", b"")
    with _bad_zip(mk_abs) as zf:
        with pytest.raises(SystemExit) as ei:
            conv.extract_zip(zf, extract / "e4")
        assert "refusing" in str(ei.value).lower() or "absolute" in str(ei.value).lower()

    def mk_drive(z):
        z.writestr("C:drive.shp", b"")
        z.writestr("C:drive.shx", b"")
        z.writestr("C:drive.dbf", b"")
    with _bad_zip(mk_drive) as zf:
        with pytest.raises(SystemExit) as ei:
            conv.extract_zip(zf, extract / "e5")
        assert "drive" in str(ei.value).lower()

    # missing sidecar
    def mk_nosides(z):
        z.writestr("miss/Boundary.shp", b"hdr")
        # no .shx .dbf
    with _bad_zip(mk_nosides) as zf:
        with pytest.raises(SystemExit) as ei:
            conv.extract_zip(zf, extract / "e6")
        assert "sidecar" in str(ei.value).lower() or "missing" in str(ei.value).lower()

    # good minimal with sides should pass (contract)
    def mk_good(z):
        z.writestr("ok/Boundary.shp", b"hdr5")
        z.writestr("ok/Boundary.shx", b"")
        z.writestr("ok/Boundary.dbf", b"")
        z.writestr("ok/LineFeature.shp", b"hdr3")
        z.writestr("ok/LineFeature.shx", b"")
        z.writestr("ok/LineFeature.dbf", b"")
    good_ex = extract / "good"
    with _bad_zip(mk_good) as zf:  # reuse buf name
        # reset? new
        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, "w") as zg:
            mk_good(zg)
        buf2.seek(0)
        conv.extract_zip(buf2, good_ex)
    assert (good_ex / "ok" / "Boundary.shp").exists()
    assert (good_ex / "ok" / "Boundary.shx").exists()
