# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the PCM archive builder (offline)."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_pcm  # noqa: E402


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    return build_pcm.build_archive(tmp_path / "pkg.zip")


def test_layout_matches_pcm_plugin_structure(archive: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        names = set(z.namelist())
    assert {"metadata.json", "plugins/plugin.json", "plugins/main.py", "plugins/requirements.txt"} <= names
    assert "plugins/jlc_footprint_importer/importer.py" in names
    assert all(n.startswith(("plugins/", "resources/")) or n == "metadata.json" for n in names)
    assert not any("__pycache__" in n or n.endswith(".pyc") or "tests/" in n for n in names)


def test_plugin_files_are_identical_to_source(archive: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        assert z.read("plugins/plugin.json") == (ROOT / "plugin.json").read_bytes()
        assert z.read("metadata.json") == (ROOT / "packaging" / "metadata.json").read_bytes()


def test_archive_is_reproducible(tmp_path: Path) -> None:
    a = build_pcm.build_archive(tmp_path / "a.zip").read_bytes()
    b = build_pcm.build_archive(tmp_path / "b.zip").read_bytes()
    assert a == b


def test_archive_metadata_has_no_download_keys(archive: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        version = json.loads(z.read("metadata.json"))["versions"][0]
    assert not any(k.startswith("download_") for k in version)
    assert version["runtime"] == "ipc"


def test_repository_metadata_has_download_keys(archive: Path) -> None:
    meta = build_pcm.repository_metadata(archive, "https://example.com/x.zip")
    version = meta["versions"][0]
    assert version["download_url"] == "https://example.com/x.zip"
    assert len(version["download_sha256"]) == 64 and version["download_size"] == archive.stat().st_size
    assert version["install_size"] > version["download_size"]
    assert not any(k.startswith("download_") for k in build_pcm.load_metadata()["versions"][0])


def test_identifier_matches_plugin_json() -> None:
    plugin = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    assert build_pcm.load_metadata()["identifier"] == plugin["identifier"]


def test_kipy_validator_accepts_archive(archive: Path) -> None:
    validate = pytest.importorskip("kipy.packaging.validate")
    report = validate.validate(archive)
    errors = [m for m in report.messages if m.level == "error"]
    assert errors == []


def _publish(tmp_path: Path, version: str, base: str = "https://example.com/repo") -> Path:
    meta = build_pcm.load_metadata()
    meta["versions"][0]["version"] = version
    archive = build_pcm.build_archive(tmp_path / f"{version}.zip")
    package = build_pcm.repository_metadata(archive, f"https://example.com/{version}.zip", meta)
    build_pcm.write_repository(tmp_path / "repo", package, base, "Someone")
    return tmp_path / "repo"


def test_repository_files_are_consistent(tmp_path: Path) -> None:
    import hashlib

    repo = _publish(tmp_path, "1.0.0")
    repository = json.loads((repo / "repository.json").read_text(encoding="utf-8"))
    assert repository["packages"]["url"] == "https://example.com/repo/packages.json"
    assert repository["packages"]["sha256"] == hashlib.sha256((repo / "packages.json").read_bytes()).hexdigest()
    assert repository["resources"]["sha256"] == hashlib.sha256((repo / "resources.zip").read_bytes()).hexdigest()
    packages = json.loads((repo / "packages.json").read_text(encoding="utf-8"))["packages"]
    assert [p["identifier"] for p in packages] == [build_pcm.load_metadata()["identifier"]]
    assert packages[0]["versions"][0]["download_url"] == "https://example.com/1.0.0.zip"
    with zipfile.ZipFile(repo / "resources.zip") as z:
        assert z.namelist() == [f"{packages[0]['identifier']}/icon.png"]


def test_new_release_keeps_previous_versions_and_replaces_same_version(tmp_path: Path) -> None:
    _publish(tmp_path, "1.0.0")
    _publish(tmp_path, "1.1.0")
    repo = _publish(tmp_path, "1.1.0")
    versions = json.loads((repo / "packages.json").read_text(encoding="utf-8"))["packages"][0]["versions"]
    assert [v["version"] for v in versions] == ["1.1.0", "1.0.0"]


def test_packages_json_validates_against_pcm_v1_schema(tmp_path: Path) -> None:
    # KiCad parses a repository's packages.json with the v1 schema (e.g. its fixed licence list).
    jsonschema = pytest.importorskip("jsonschema")
    from importlib.resources import files

    schema = json.loads(files("kipy.packaging.schemas").joinpath("pcm.v1.schema.json").read_text(encoding="utf-8"))
    repo = _publish(tmp_path, "1.0.0")
    package = json.loads((repo / "packages.json").read_text(encoding="utf-8"))["packages"][0]
    errors = [e.message for e in jsonschema.Draft7Validator(schema).iter_errors(package)]
    assert errors == []
