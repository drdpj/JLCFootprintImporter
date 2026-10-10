# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the stock footprint check and the pad-geometry duplicate check."""

from __future__ import annotations

from pathlib import Path

from jlc_footprint_importer.cache import find_cached_part
from jlc_footprint_importer.config import LibraryPaths
from jlc_footprint_importer.easyeda_backend import FailureKind, Parts
from jlc_footprint_importer.geometry import compare_footprints
from jlc_footprint_importer.importer import FootprintChoice, Status, import_part
from jlc_footprint_importer.partinfo import PartInfo, parse_part_info
from jlc_footprint_importer.sexpr import parse
from jlc_footprint_importer.stock_check import (
    KicadStockFootprintChecker,
    NullStockFootprintChecker,
    guess_stock_footprint,
)

from .conftest import TWO_PADS, FakeBackend, footprint_text

WIDER_PADS = TWO_PADS.replace("0.800 0.864", "1.000 0.900")
THREE_PADS = TWO_PADS + "\t(pad 3 smd rect (at 0 1) (size 0.8 0.8) (layers F.Cu))\n"


def _part(package: str, prefix: str, lcsc: str = "C21190") -> PartInfo:
    return PartInfo(lcsc, package=package, prefix=prefix, footprint_name=package)


def _stock_dir(tmp_path: Path, *footprints: str) -> Path:
    root = tmp_path / "stock"
    for lib_id in footprints:
        lib, name = lib_id.split(":")
        (root / f"{lib}.pretty").mkdir(parents=True, exist_ok=True)
        (root / f"{lib}.pretty" / f"{name}.kicad_mod").write_text("(footprint)", encoding="utf-8")
    return root


# --- geometry -------------------------------------------------------------------------


def test_identical_pads_ignore_everything_else() -> None:
    other = footprint_text(lcsc="C2").replace("a \\\"quoted\\\" thing", "different").replace("REF**", "R1")
    assert compare_footprints(footprint_text(), other) == []


def test_pad_order_and_equivalent_rotation_do_not_matter() -> None:
    a = footprint_text(pads=TWO_PADS)
    b = footprint_text(pads=TWO_PADS.replace("180.00", "0").replace("0.800 0.864", "0.800 0.864"))
    reordered = footprint_text(pads="".join(reversed(TWO_PADS.splitlines(keepends=True))))
    assert compare_footprints(a, b) == []
    assert compare_footprints(a, reordered) == []


def test_ninety_degree_rotation_is_equivalent_to_swapped_size() -> None:
    a = footprint_text(pads="\t(pad 1 smd rect (at 0 0 90) (size 0.5 1.0) (layers F.Cu))\n")
    b = footprint_text(pads="\t(pad 1 smd rect (at 0 0) (size 1.0 0.5) (layers F.Cu))\n")
    assert compare_footprints(a, b) == []


def test_different_pad_size_is_reported() -> None:
    diffs = compare_footprints(footprint_text(), footprint_text(pads=WIDER_PADS))
    assert any("library has pad 1" in d for d in diffs)
    assert any("new part has pad 1" in d and "1x0.9" in d for d in diffs)


def test_different_pad_count_is_reported() -> None:
    diffs = compare_footprints(footprint_text(), footprint_text(pads=THREE_PADS))
    assert diffs[0] == "pad count differs (2 in the library, 3 in the new part)"


def test_quoted_pad_numbers_and_drills_are_understood() -> None:
    thru = '\t(pad "1" thru_hole circle (at 0 0) (size 1.6 1.6) (drill 0.8) (layers *.Cu *.Mask))\n'
    assert compare_footprints(footprint_text(pads=thru), footprint_text(pads=thru)) == []
    assert compare_footprints(footprint_text(pads=thru), footprint_text(pads=thru.replace("0.8)", "1.0)")))


# --- stock check ----------------------------------------------------------------------


def test_guess_maps_prefix_and_size_to_kicad_names() -> None:
    assert guess_stock_footprint(_part("R0603", "R"))[:2] == ("Resistor_SMD", "R_0603_1608Metric")
    assert guess_stock_footprint(_part("C0402", "C"))[:2] == ("Capacitor_SMD", "C_0402_1005Metric")
    assert guess_stock_footprint(_part("L0603", "L"))[:2] == ("Inductor_SMD", "L_0603_1608Metric")
    assert guess_stock_footprint(_part("LED0805-R-RD", "LED"))[:2] == ("LED_SMD", "LED_0805_2012Metric")
    assert guess_stock_footprint(_part("0805", "R"))[:2] == ("Resistor_SMD", "R_0805_2012Metric")


def test_guess_rejects_non_chip_packages_and_unknown_kinds() -> None:
    assert guess_stock_footprint(_part("SOT-23", "Q")) is None
    assert guess_stock_footprint(_part("CONN-TH_DIN-319", "CN")) is None
    assert guess_stock_footprint(_part("R0603", "U")) is None  # package says R but it is not a resistor
    assert guess_stock_footprint(_part("R9999", "R")) is None


def test_checker_only_matches_footprints_that_exist(tmp_path: Path) -> None:
    present = KicadStockFootprintChecker([_stock_dir(tmp_path, "Resistor_SMD:R_0603_1608Metric")])
    match = present.find_stock_footprint(_part("R0603", "R"))
    assert match is not None and match.lib_id == "Resistor_SMD:R_0603_1608Metric"
    assert present.find_stock_footprint(_part("R0805", "R")) is None
    assert KicadStockFootprintChecker([tmp_path / "nowhere"]).find_stock_footprint(_part("R0603", "R")) is None
    assert NullStockFootprintChecker().find_stock_footprint(_part("R0603", "R")) is None


def test_parse_part_info_reads_reference_prefix() -> None:
    info = parse_part_info("C1", {"dataStr": {"head": {"c_para": {"pre": "R?", "package": "R0603"}}}})
    assert info.prefix == "R"


# --- importer: stock footprint flow ----------------------------------------------------


def _stock_setup(tmp_path: Path) -> tuple[KicadStockFootprintChecker, PartInfo]:
    checker = KicadStockFootprintChecker([_stock_dir(tmp_path, "Resistor_SMD:R_0603_1608Metric")])
    return checker, _part("R0603", "R")


def test_stock_footprint_is_offered_and_nothing_is_imported(project: Path, tmp_path: Path) -> None:
    checker, info = _stock_setup(tmp_path)
    backend = FakeBackend()
    result = import_part(project, "C21190", backend=backend, part_lookup=lambda _i: info, stock_checker=checker)
    assert result.status is Status.STOCK_AVAILABLE and result.ok
    assert result.stock is not None and result.stock.lib_id == "Resistor_SMD:R_0603_1608Metric"
    assert "Resistor_SMD:R_0603_1608Metric" in result.message
    assert backend.calls == []
    assert not LibraryPaths(project).footprint_dir.exists()


def test_choosing_stock_imports_symbol_only_with_stock_footprint(project: Path, tmp_path: Path) -> None:
    checker, info = _stock_setup(tmp_path)
    backend = FakeBackend()
    result = import_part(
        project, "C21190", backend=backend, part_lookup=lambda _i: info,
        stock_checker=checker, choice=FootprintChoice.STOCK,
    )
    assert result.status is Status.IMPORTED
    paths = LibraryPaths(project)
    assert backend.parts == [Parts.SYMBOL]
    assert not paths.footprint_dir.exists()
    symbol = parse(paths.symbol_file.read_text(encoding="utf-8")).find("symbol")
    props = {p.atom_args()[0]: p.atom_args()[1] for p in symbol.find_all("property")}
    assert props["Footprint"] == "Resistor_SMD:R_0603_1608Metric"
    assert props["LCSC Part"] == "C21190"
    assert paths.sym_lib_table.is_file() and not paths.fp_lib_table.exists()


def test_stock_import_is_cached_on_repeat(project: Path, tmp_path: Path) -> None:
    checker, info = _stock_setup(tmp_path)
    kwargs = dict(part_lookup=lambda _i: info, stock_checker=checker)
    import_part(project, "C21190", backend=FakeBackend(), choice=FootprintChoice.STOCK, **kwargs)
    again = FakeBackend()
    result = import_part(project, "C21190", backend=again, **kwargs)
    assert result.status is Status.CACHED and "stock footprint Resistor_SMD:R_0603_1608Metric" in result.message
    assert again.calls == []
    cached = find_cached_part(LibraryPaths(project), "C21190")
    assert cached.uses_stock_footprint and not cached.complete


def test_choosing_jlc_skips_the_stock_offer(project: Path, tmp_path: Path) -> None:
    checker, info = _stock_setup(tmp_path)
    backend = FakeBackend()
    result = import_part(
        project, "C21190", backend=backend, part_lookup=lambda _i: info,
        stock_checker=checker, choice=FootprintChoice.JLC,
    )
    assert result.status is Status.IMPORTED and backend.parts == [Parts.FULL]
    assert LibraryPaths(project).footprint_dir.is_dir()


def test_no_stock_match_goes_straight_to_jlc_import(project: Path, tmp_path: Path) -> None:
    checker = KicadStockFootprintChecker([tmp_path / "nowhere"])
    result = import_part(
        project, "C21190", backend=FakeBackend(), part_lookup=lambda _i: _part("R0603", "R"), stock_checker=checker
    )
    assert result.status is Status.IMPORTED


def test_stock_choice_without_a_match_fails_cleanly(project: Path) -> None:
    result = import_part(
        project, "C21190", backend=FakeBackend(), part_lookup=lambda _i: _part("R0603", "R"),
        stock_checker=NullStockFootprintChecker(), choice=FootprintChoice.STOCK,
    )
    assert result.status is Status.FAILED


# --- importer: geometry duplicate check -----------------------------------------------


def _import_first(project: Path) -> None:
    info = _part("R0603", "R", "C1")
    assert import_part(project, "C1", backend=FakeBackend(), part_lookup=lambda _i: info).status is Status.IMPORTED


def test_same_name_different_pads_is_a_conflict(project: Path) -> None:
    _import_first(project)
    backend = FakeBackend(pads=WIDER_PADS)
    result = import_part(project, "C2", backend=backend, part_lookup=lambda _i: _part("R0603", "R", "C2"))
    assert result.status is Status.CONFLICT and not result.ok
    assert "differ" in result.message and "1x0.9" in result.message and "imported as C1" in result.message
    assert "C2" not in LibraryPaths(project).symbol_file.read_text(encoding="utf-8")
    assert "1.000" not in (LibraryPaths(project).footprint_dir / "R0603.kicad_mod").read_text(encoding="utf-8")


def test_same_name_same_pads_is_a_duplicate(project: Path) -> None:
    _import_first(project)
    result = import_part(project, "C2", backend=FakeBackend(), part_lookup=lambda _i: _part("R0603", "R", "C2"))
    assert result.status is Status.DUPLICATE and "identical pads" in result.message


def test_duplicate_check_degrades_when_comparison_fetch_fails(project: Path) -> None:
    _import_first(project)
    failing = FakeBackend(ok=False, failure=FailureKind.NETWORK)
    result = import_part(project, "C2", backend=failing, part_lookup=lambda _i: _part("R0603", "R", "C2"))
    assert result.status is Status.DUPLICATE
    assert "could not be compared" in result.message
