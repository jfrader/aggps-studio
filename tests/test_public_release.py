from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_examples_directory_is_absent_or_empty() -> None:
    examples = ROOT / "examples"
    assert not examples.exists() or not any(examples.iterdir())


def test_public_license_metadata_and_notice() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    assert 'license = "GPL-3.0-or-later"' in pyproject
    assert "Copyright © 2026 Fran <jfrader@pm.me>" in readme
    assert license_text.startswith("                    GNU GENERAL PUBLIC LICENSE\n")
    assert "Version 3, 29 June 2007" in license_text


def test_desktop_notice_generator_is_pinned_and_generated_output_is_ignored() -> None:
    build_requirements = (ROOT / "requirements-build-desktop.txt").read_text(
        encoding="utf-8"
    )
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "pip-licenses==5.5.5" in build_requirements
    assert "THIRD_PARTY_NOTICES.txt" in gitignore.splitlines()
