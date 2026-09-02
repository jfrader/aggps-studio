from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "workflow_path",
    [Path(".github/workflows/ci.yml"), Path(".github/workflows/release.yml")],
)
def test_windows_jobs_run_frozen_gui_smoke_with_diagnostic_markers(
    workflow_path: Path,
) -> None:
    workflow = workflow_path.read_text(encoding="utf-8")
    windows_smoke = workflow.split("- name: Run Windows GUI smoke", 1)[1].split(
        "- name: Upload desktop artifact", 1
    )[0]

    assert '"dist\\AgGPS Studio\\AgGPS Studio.exe"' in windows_smoke
    assert "Test-Path -LiteralPath $exe" in windows_smoke
    assert "$env:RUNNER_TEMP" in windows_smoke
    assert "New-Item -ItemType Directory -Path $verifyDir" in windows_smoke
    assert "$env:AGGPS_DESKTOP_VERIFY_DIR = $verifyDir" in windows_smoke
    assert "& $exe --gui-smoke-test" in windows_smoke
    assert "$exitCode = $LASTEXITCODE" in windows_smoke
    assert ".aggps-gui-smoke-ok" in windows_smoke
    assert ".aggps-gui-smoke-error" in windows_smoke
    assert "Get-Content -LiteralPath $errorMarker -Raw" in windows_smoke
    diagnostic_index = windows_smoke.index(
        "Get-Content -LiteralPath $errorMarker -Raw"
    )
    throw_index = windows_smoke.index('throw "Windows GUI smoke test failed')
    assert diagnostic_index < throw_index
    assert "Test-Path -LiteralPath $successMarker" in windows_smoke
    assert '$successText -ne "OK"' in windows_smoke


def test_ci_replaces_import_only_windows_probe() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Probe Windows GUI backend" not in workflow
    assert "from webview.platforms import edgechromium, winforms" not in workflow


def test_tag_release_waits_for_verified_platform_bundles() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    publish_job = workflow.split("\n  publish-release:", 1)[1]

    assert 'tags:\n      - "v*"' in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "\n    permissions:\n      contents: write" in publish_job
    assert workflow.count("contents: write") == 1
    assert "windows-x64" in workflow and "linux-x64" in workflow
    assert "tag == f'v{APP_VERSION}'" in workflow
    assert "python build_desktop.py --verify" in workflow
    assert "tests/test_packaging.py" in workflow
    assert "--gui-smoke-test" in workflow
    assert '"dist\\AgGPS Studio\\AgGPS Studio.exe"' in workflow
    assert "Test-Path -LiteralPath $exe" in workflow
    assert "& $exe --gui-smoke-test" in workflow
    assert "$exitCode = $LASTEXITCODE" in workflow
    assert "$exitCode -ne 0" in workflow
    assert ".aggps-gui-smoke-ok" in workflow
    assert ".aggps-gui-smoke-error" in workflow
    assert "edgechromium, winforms" not in workflow
    assert "path: dist/aggps-studio-*-${{ matrix.plat }}.zip" in workflow
    assert "needs: build-desktop" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "gh release create" in workflow
    assert "GH_REPO: ${{ github.repository }}" in publish_job
    assert "--generate-notes" in workflow
