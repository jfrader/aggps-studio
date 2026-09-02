from pathlib import Path


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
    assert "$LASTEXITCODE -ne 0" in workflow
    assert "edgechromium, winforms" not in workflow
    assert "path: dist/aggps-studio-*-${{ matrix.plat }}.zip" in workflow
    assert "needs: build-desktop" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "gh release create" in workflow
    assert "GH_REPO: ${{ github.repository }}" in publish_job
    assert "--generate-notes" in workflow
