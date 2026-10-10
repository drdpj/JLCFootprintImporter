# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from jlc_footprint_importer.config import LibraryPaths
from jlc_footprint_importer.easyeda_backend import Parts
from jlc_footprint_importer.importer import Status, import_part
from jlc_footprint_importer.partinfo import PartInfo, parse_part_info
from jlc_footprint_importer.provenance import (
    apply_part_info_to_footprint,
    apply_part_info_to_symbol_library,
)
from jlc_footprint_importer.sexpr import parse

from .conftest import FakeBackend, footprint_text, symbol_lib_text

API_RESULT = {
    "title": "GZ1608D601TF",
    "description": "600Ω ±25% 100MHz",
    "tags": ["Ferrite Beads"],
    "dataStr": {
        "head": {
            "c_para": {
                "package": "L0603",
                "Manufacturer": "Sunlord(顺络)",
                "Manufacturer Part": "GZ1608D601TF",
                "JLCPCB Part Class": "Basic Part",
            }
        }
    },
}
INFO = parse_part_info("C1002", API_RESULT)


def test_parse_part_info_and_description() -> None:
    assert INFO.category == "Ferrite Beads"
    assert INFO.manufacturer == "Sunlord"
    assert INFO.description == (
        "Ferrite Beads 600Ω ±25% 100MHz, L0603 package, Sunlord GZ1608D601TF [LCSC C1002, JLCPCB Basic Part]"
    )


def test_parse_part_info_tolerates_missing_fields() -> None:
    info = parse_part_info("C1", {})
    assert info.description == "[LCSC C1]"


def test_footprint_description_tags_and_properties() -> None:
    out = apply_part_info_to_footprint(footprint_text(), INFO)
    root = parse(out)
    assert root.find("descr").atom_args() == [INFO.description]
    assert "Ferrite Beads" in root.find("tags").atom_args()[0]
    props = {n.atom_args()[0]: n.atom_args()[1] for n in root.find_all("property")}
    assert props["Category"] == "Ferrite Beads"
    assert props["MPN"] == "GZ1608D601TF"
    assert props["JLCPCB Part Class"] == "Basic Part"
    assert apply_part_info_to_footprint(out, INFO) == out


def test_symbol_description_updated_only_for_matching_part() -> None:
    text = symbol_lib_text({"A": "C1002", "B": "C9"}).replace(
        '(property "LCSC Part" "C1002" (at 0 0 0))',
        '(property "LCSC Part" "C1002" (at 0 0 0))\n    (property "ki_description" "raw" (at 0 0 0))',
    ).replace(
        '(property "LCSC Part" "C9" (at 0 0 0))',
        '(property "LCSC Part" "C9" (at 0 0 0))\n    (property "ki_description" "raw" (at 0 0 0))',
    )
    out = apply_part_info_to_symbol_library(text, "C1002", INFO)
    descs = [
        [p.atom_args()[1] for p in s.find_all("property") if p.atom_args()[0] == "ki_description"][0]
        for s in parse(out).find_all("symbol")
    ]
    assert descs == [INFO.description, "raw"]


def test_import_applies_part_info(project) -> None:
    result = import_part(project, "C1002", backend=FakeBackend(name="L0603"), part_lookup=lambda _id: INFO)
    assert result.status is Status.IMPORTED and not result.warnings
    text = (LibraryPaths(project).footprint_dir / "L0603.kicad_mod").read_text(encoding="utf-8")
    assert parse(text).find("descr").atom_args() == [INFO.description]


def test_import_warns_but_succeeds_when_lookup_fails(project) -> None:
    result = import_part(project, "C1002", backend=FakeBackend(), part_lookup=lambda _id: None)
    assert result.status is Status.IMPORTED
    assert any("part details" in w for w in result.warnings)


def test_partinfo_is_a_dataclass_default() -> None:
    assert PartInfo("C1").extra_properties() == {}


def test_same_footprint_as_existing_part_is_not_imported(project) -> None:
    import_part(project, "C1002", backend=FakeBackend(name="L0603"), part_lookup=lambda _id: INFO)
    other = FakeBackend(name="L0603")
    info = PartInfo("C9999", footprint_name="L0603")
    result = import_part(project, "C9999", backend=other, part_lookup=lambda _id: info)
    assert result.status is Status.DUPLICATE and result.ok
    assert "L0603" in result.message and "C1002" in result.message
    assert "identical pads" in result.message
    assert other.parts == [Parts.FOOTPRINT]  # only fetched for comparison, nothing imported
    paths = LibraryPaths(project)
    assert "C9999" not in paths.symbol_file.read_text(encoding="utf-8")


def test_different_footprint_name_still_imports(project) -> None:
    import_part(project, "C1002", backend=FakeBackend(name="L0603"), part_lookup=lambda _id: INFO)
    info = PartInfo("C9999", footprint_name="R0805")
    backend = FakeBackend(name="R0805")
    result = import_part(project, "C9999", backend=backend, part_lookup=lambda _id: info)
    assert result.status is Status.IMPORTED and len(backend.calls) == 1
