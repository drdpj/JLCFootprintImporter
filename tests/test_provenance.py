# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import datetime as dt
from pathlib import Path

from jlc_footprint_importer.config import LibraryPaths
from jlc_footprint_importer.importer import Status, import_part
from jlc_footprint_importer.provenance import (
    Provenance,
    add_footprint_properties,
    use_project_relative_model_path,
)
from jlc_footprint_importer.sexpr import parse

from .conftest import FakeBackend, footprint_text

PROV = Provenance.now("C21190", dt.date(2026, 10, 10))


def _props(text: str) -> dict[str, str]:
    return {n.atom_args()[0]: n.atom_args()[1] for n in parse(text).find_all("property")}


def test_properties_added_with_expected_values() -> None:
    props = _props(add_footprint_properties(footprint_text(lcsc=None), PROV))
    assert props == {
        "LCSC": "C21190",
        "Source": "easyeda2kicad / LCSC",
        "Import Date": "2026-10-10",
    }


def test_existing_properties_kept_and_operation_idempotent() -> None:
    once = add_footprint_properties(footprint_text(), PROV)
    assert _props(once)["LCSC Part"] == "C21190"
    assert add_footprint_properties(once, PROV) == once


def test_rest_of_footprint_untouched() -> None:
    original = footprint_text()
    updated = add_footprint_properties(original, PROV)
    assert '(descr "a \\"quoted\\" thing")' in updated
    assert parse(updated).find("model") is not None


def test_model_path_made_project_relative() -> None:
    text = footprint_text(model_dir="C:/proj/jlc-libs/jlc.3dshapes")
    out = use_project_relative_model_path(
        text, Path("C:/proj/jlc-libs/jlc.3dshapes"), "${KIPRJMOD}/jlc-libs/jlc.3dshapes"
    )
    assert '"${KIPRJMOD}/jlc-libs/jlc.3dshapes/R0603.wrl"' in out


def test_custom_fields_for_symbols() -> None:
    assert PROV.easyeda_custom_fields() == [
        "LCSC:C21190",
        "Source:easyeda2kicad / LCSC",
        "Import Date:2026-10-10",
    ]


def test_import_stamps_footprint_registers_tables_and_passes_fields(project: Path) -> None:
    backend = FakeBackend()
    result = import_part(project, " c21190 ", backend, today=dt.date(2026, 10, 10))
    assert result.status is Status.IMPORTED, result.message
    paths = LibraryPaths(project)
    text = (paths.footprint_dir / "R0603.kicad_mod").read_text(encoding="utf-8")
    assert _props(text)["Import Date"] == "2026-10-10"
    assert "${KIPRJMOD}/jlc-libs/jlc.3dshapes/R0603.wrl" in text
    assert "jlc.pretty" in paths.fp_lib_table.read_text(encoding="utf-8")
    assert "jlc.kicad_sym" in paths.sym_lib_table.read_text(encoding="utf-8")
    lcsc_id, output_base, fields = backend.calls[0]
    assert lcsc_id == "C21190" and output_base == paths.output_base
    assert "Import Date:2026-10-10" in fields
