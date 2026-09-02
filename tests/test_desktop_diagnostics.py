from pathlib import Path

import pytest

import desktop


def test_gui_smoke_diagnostic_wrapper_preserves_success_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def successful_gui_smoke() -> None:
        desktop._write_ci_marker(".aggps-gui-smoke-ok", "OK")

    monkeypatch.setenv("AGGPS_DESKTOP_VERIFY_DIR", str(tmp_path))
    monkeypatch.setattr(desktop, "_run_gui_smoke_test", successful_gui_smoke)

    assert desktop._run_gui_smoke_test_with_diagnostics() == 0
    assert (tmp_path / ".aggps-gui-smoke-ok").read_text(
        encoding="utf-8"
    ).strip() == "OK"
    assert not (tmp_path / ".aggps-gui-smoke-error").exists()


def test_gui_smoke_diagnostic_wrapper_writes_sanitized_error_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_gui_smoke() -> None:
        raise RuntimeError("native backend failed token=do-not-leak")

    monkeypatch.setenv("AGGPS_DESKTOP_VERIFY_DIR", str(tmp_path))
    monkeypatch.setattr(desktop, "_run_gui_smoke_test", fail_gui_smoke)

    assert desktop._run_gui_smoke_test_with_diagnostics() == 1
    assert (tmp_path / ".aggps-gui-smoke-error").read_text(
        encoding="utf-8"
    ).strip() == "RuntimeError: native backend failed token=<redacted>"
    assert not (tmp_path / ".aggps-gui-smoke-ok").exists()
