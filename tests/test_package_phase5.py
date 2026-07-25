from __future__ import annotations

from importlib import metadata
from pathlib import Path
import tomllib

from manufacturing_monitor import __version__
from manufacturing_monitor import cli


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_NAME = "manufacturing-economic-monitor"


def _pyproject() -> dict[str, object]:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_package_version_is_available_and_consistent():
    project = _pyproject()["project"]

    assert __version__ == "0.2.0"
    assert project["version"] == __version__
    assert metadata.version(DIST_NAME) == __version__


def test_project_info_output_reports_version_without_network(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_application_workflow", lambda *_args, **_kwargs: None)

    cli.main(["--project-info"])

    output = capsys.readouterr().out
    assert "Manufacturing Economic Monitor" in output
    assert f"Version: {__version__}" in output
    assert "Network: not contacted" in output


def test_console_entry_point_matches_installed_distribution():
    scripts = metadata.entry_points(group="console_scripts")
    entry_point = next(item for item in scripts if item.name == "manufacturing-monitor")

    assert entry_point.dist is not None
    assert entry_point.dist.metadata["Name"] == DIST_NAME
    assert entry_point.value == "manufacturing_monitor.cli:main"


def test_distribution_metadata_matches_pyproject():
    project = _pyproject()["project"]
    dist_metadata = metadata.metadata(DIST_NAME)

    assert dist_metadata["Name"] == project["name"]
    assert dist_metadata["Version"] == project["version"]
    assert dist_metadata["Author-email"] == "Mohammadreza Ensafi <mze0069@auburn.edu>"
    assert "Repository, https://github.com/Mze0069/manufacturing-economic-monitor" in (
        dist_metadata.get_all("Project-URL") or []
    )
    assert "Issues, https://github.com/Mze0069/manufacturing-economic-monitor/issues" in (
        dist_metadata.get_all("Project-URL") or []
    )
    assert dist_metadata.get_all("License-File") is None


def test_no_secret_placeholders_are_embedded_in_packaged_sources_or_metadata():
    forbidden_fragments = (
        "FAKE_SECRET_DO_NOT_PRINT",
        "your_fred_api_key",
        "your-fred-api-key",
        "api_key_here",
    )
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "src" / "manufacturing_monitor").glob("*.py")
    )
    dist_metadata = metadata.metadata(DIST_NAME)
    metadata_text = "\n".join(
        value
        for key in dist_metadata
        for value in (dist_metadata.get_all(key) or [])
    )

    for fragment in forbidden_fragments:
        assert fragment not in source_text
        assert fragment not in metadata_text


def test_build_configuration_excludes_generated_and_sensitive_content():
    build_config = _pyproject()["tool"]["uv"]["build-backend"]
    source_exclude = set(build_config["source-exclude"])
    wheel_exclude = set(build_config["wheel-exclude"])

    assert "/.env" in source_exclude
    assert "/.env.*" in source_exclude
    assert "/data" in source_exclude
    assert "/dist" in source_exclude
    assert "/build" in source_exclude
    assert "/logs" in source_exclude
    assert "*.db" in wheel_exclude
    assert "*.sqlite" in wheel_exclude
    assert "*.sqlite3" in wheel_exclude
    assert "*.csv" in wheel_exclude
