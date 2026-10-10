# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path

from jlc_footprint_importer.cache import find_cached_part
from jlc_footprint_importer.config import LibraryPaths
from jlc_footprint_importer.easyeda_backend import FailureKind
from jlc_footprint_importer.importer import Status, import_part

from .conftest import FakeBackend, footprint_text, symbol_lib_text


def _seed(paths: LibraryPaths, fp_lcsc: str | None, sym_lcsc: str | None) -> None:
    paths.footprint_dir.mkdir(parents=True)
    if fp_lcsc:
        (paths.footprint_dir / "R0603.kicad_mod").write_text(footprint_text(lcsc=fp_lcsc), encoding="utf-8")
    if sym_lcsc:
        paths.symbol_file.write_text(symbol_lib_text({"R0603": sym_lcsc}), encoding="utf-8")


def test_empty_project_is_not_cached(project: Path) -> None:
    assert not find_cached_part(LibraryPaths(project), "C21190").found_any


def test_complete_part_detected(project: Path) -> None:
    paths = LibraryPaths(project)
    _seed(paths, "C21190", "C21190")
    part = find_cached_part(paths, "c21190")
    assert part.complete and part.footprints == ("R0603",) and part.symbols == ("R0603",)


def test_other_id_not_matched(project: Path) -> None:
    paths = LibraryPaths(project)
    _seed(paths, "C21190", "C21190")
    assert not find_cached_part(paths, "C2119").found_any  # no substring matches


def test_partial_part_detected(project: Path) -> None:
    paths = LibraryPaths(project)
    _seed(paths, "C21190", None)
    part = find_cached_part(paths, "C21190")
    assert part.found_any and not part.complete


def test_unparseable_files_are_skipped(project: Path) -> None:
    paths = LibraryPaths(project)
    _seed(paths, None, None)
    (paths.footprint_dir / "bad.kicad_mod").write_text("(module C21190 (", encoding="utf-8")
    assert not find_cached_part(paths, "C21190").found_any


def test_import_skips_backend_when_cached(project: Path) -> None:
    _seed(LibraryPaths(project), "C21190", "C21190")
    backend = FakeBackend()
    result = import_part(project, "C21190", backend)
    assert result.status is Status.CACHED and "already" in result.message
    assert backend.calls == []


def test_second_import_of_same_part_hits_cache(project: Path) -> None:
    backend = FakeBackend()
    assert import_part(project, "C21190", backend).status is Status.IMPORTED
    assert import_part(project, "C21190", backend).status is Status.CACHED
    assert len(backend.calls) == 1


def test_partial_cache_is_reported_not_downloaded(project: Path) -> None:
    _seed(LibraryPaths(project), "C21190", None)
    backend = FakeBackend()
    result = import_part(project, "C21190", backend)
    assert result.status is Status.FAILED and "partly" in result.message
    assert backend.calls == []


def test_failure_messages_are_friendly(project: Path) -> None:
    for kind, text in [
        (FailureKind.NETWORK, "internet"),
        (FailureKind.NOT_FOUND, "no data"),
        (FailureKind.ALREADY_EXISTS, "already exists"),
    ]:
        result = import_part(project, "C1", FakeBackend(ok=False, failure=kind))
        assert result.status is Status.FAILED
        assert text in result.message.lower()
        assert "Traceback" not in result.message


def test_invalid_id_rejected_without_backend(project: Path) -> None:
    backend = FakeBackend()
    assert import_part(project, "R0603", backend).status is Status.FAILED
    assert backend.calls == []
