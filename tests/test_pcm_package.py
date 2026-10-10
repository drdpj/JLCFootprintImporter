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
