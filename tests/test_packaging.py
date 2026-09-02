"""Packaging verification tests for desktop onedir zips.

These run after `python build_desktop.py` (or in CI matrix jobs).
They assert:
- ZIP contains exactly one top-level folder named "AgGPS Studio"
- executable present ( .exe on win, bare on linux)
- templates/ and static/ present inside the frozen onedir layout
- project and third-party license notices present beside the executable
- no customer inputs, jobs/, caches, or project source/dev files packaged

Run:
  python -m pytest tests/test_packaging.py -q
(requires the zips in ./dist/ from a prior build)
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import build_desktop


def _find_current_zip() -> Path:
    """Find the ZIP for the platform that was actually built on this runner.
    Each matrix job produces only its own artifact, so tests must not assume both.
    """
    wins = list(Path("dist").glob("aggps-studio-*-windows-x64.zip"))
    lins = list(Path("dist").glob("aggps-studio-*-linux-x64.zip"))
    if wins:
        return wins[0]
    if lins:
        return lins[0]
    pytest.skip("no desktop zip found in dist/ (run build_desktop.py first for desktop matrix)")

def _is_windows_zip(zp: Path) -> bool:
    return "windows" in zp.name

def test_desktop_zip_has_exactly_one_app_folder() -> None:
    zp = _find_current_zip()
    with zipfile.ZipFile(zp) as z:
        nl = [n for n in z.namelist() if n.strip()]
        tops = {n.split("/")[0] for n in nl}
        assert len(tops) == 1, f"expected 1 top-level dir, got {tops}"
        assert list(tops)[0] == "AgGPS Studio"

def test_desktop_zip_executable_and_resources() -> None:
    zp = _find_current_zip()
    with zipfile.ZipFile(zp) as z:
        nl = z.namelist()
        if _is_windows_zip(zp):
            assert any(n.endswith("AgGPS Studio.exe") for n in nl)
        else:
            assert any("AgGPS Studio/AgGPS Studio" in n for n in nl)
        assert any("templates/index.html" in n for n in nl)
        assert any("static/app.js" in n for n in nl) or any("static/app.css" in n for n in nl)
        assert "AgGPS Studio/BUNDLE_README.txt" in nl
        assert b"THIRD_PARTY_NOTICES.txt" in z.read(
            "AgGPS Studio/BUNDLE_README.txt"
        )
        assert "AgGPS Studio/LICENSE.txt" in nl
        assert "AgGPS Studio/THIRD_PARTY_NOTICES.txt" in nl
        assert z.getinfo("AgGPS Studio/THIRD_PARTY_NOTICES.txt").file_size >= 1_000


def test_notice_generator_uses_piplicenses_embedded_text_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_check_call(command: list[str], cwd: Path) -> None:
        captured["command"] = command
        captured["cwd"] = cwd
        output_path = Path(command[command.index("--output-file") + 1])
        package_blocks = [
            f"{name}\n1.0\nLicense\n{'license text ' * 20}\nUNKNOWN\n"
            for name in sorted(build_desktop.REQUIRED_NOTICE_PACKAGES)
        ]
        output_path.write_text("\n".join(package_blocks), encoding="utf-8")

    monkeypatch.setattr(build_desktop.subprocess, "check_call", fake_check_call)

    notices_path = build_desktop._generate_third_party_notices(tmp_path)

    command = captured["command"]
    assert isinstance(command, list)
    assert command[1:3] == ["-m", "piplicenses"]
    assert "--from=all" in command
    assert "--order=name" in command
    assert "--format=plain-vertical" in command
    assert "--with-license-file" in command
    assert "--no-license-path" in command
    assert "--with-notice-file" in command
    assert captured["cwd"] == tmp_path
    assert notices_path == tmp_path / "THIRD_PARTY_NOTICES.txt"


def test_notice_generator_rejects_incomplete_inventory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_check_call(command: list[str], cwd: Path) -> None:
        del cwd
        output_path = Path(command[command.index("--output-file") + 1])
        output_path.write_text("unrelated package\n" * 100, encoding="utf-8")

    monkeypatch.setattr(build_desktop.subprocess, "check_call", fake_check_call)

    with pytest.raises(RuntimeError, match="missing bundled runtime packages"):
        build_desktop._generate_third_party_notices(tmp_path)

def test_desktop_zip_contains_no_customer_or_source_artifacts() -> None:
    zp = _find_current_zip()
    with zipfile.ZipFile(zp) as z:
        nl = z.namelist()
        forbidden = [
            "jobs/", "_jobs/", "input.zip", ".git/", "tests/", "AgGPS.zip",
            "customer", "cache/", "__pycache__/",
        ]
        bad = [n for n in nl if any(f in n for f in forbidden)]
        assert not bad, f"runtime zip must not contain customer/source/caches: {bad[:3]}"
