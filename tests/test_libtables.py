# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path

import pytest

from jlc_footprint_importer.libtables import (
    FP_TABLE_HEAD,
    LibEntry,
    LibraryTableError,
    ensure_library,
    read_entries,
)

ENTRY = LibEntry("jlc", "${KIPRJMOD}/jlc-libs/jlc.pretty", descr="d")

EXISTING = (
    "(fp_lib_table\n"
    "  (version 7)\n"
    '  (lib (name "Mine")(type "KiCad")(uri "${KIPRJMOD}/mine.pretty")(options "")(descr "x (y)"))\n'
    ")\n"
)


def test_creates_missing_table(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    assert ensure_library(table, FP_TABLE_HEAD, ENTRY) is True
    assert [e.name for e in read_entries(table, FP_TABLE_HEAD)] == ["jlc"]


def test_preserves_existing_entries_byte_for_byte(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    table.write_text(EXISTING, encoding="utf-8")
    assert ensure_library(table, FP_TABLE_HEAD, ENTRY) is True
    new = table.read_text(encoding="utf-8")
    assert new.startswith(EXISTING[: EXISTING.rindex(")")])
    names = [e.name for e in read_entries(table, FP_TABLE_HEAD)]
    assert names == ["Mine", "jlc"]
    assert (tmp_path / "fp-lib-table.bak").read_text(encoding="utf-8") == EXISTING


def test_no_duplicate_on_second_call(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    table.write_text(EXISTING, encoding="utf-8")
    ensure_library(table, FP_TABLE_HEAD, ENTRY)
    after_first = table.read_text(encoding="utf-8")
    assert ensure_library(table, FP_TABLE_HEAD, ENTRY) is False
    assert table.read_text(encoding="utf-8") == after_first


def test_same_uri_under_other_name_is_not_duplicated(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    table.write_text(
        EXISTING.replace("mine.pretty", "jlc-libs/jlc.pretty").replace("Mine", "Other"),
        encoding="utf-8",
    )
    assert ensure_library(table, FP_TABLE_HEAD, ENTRY) is False


def test_name_conflict_with_different_uri_raises_and_leaves_file(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    table.write_text(EXISTING.replace('"Mine"', '"jlc"'), encoding="utf-8")
    before = table.read_text(encoding="utf-8")
    with pytest.raises(LibraryTableError):
        ensure_library(table, FP_TABLE_HEAD, ENTRY)
    assert table.read_text(encoding="utf-8") == before


def test_preserves_crlf(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    table.write_bytes(EXISTING.replace("\n", "\r\n").encode())
    ensure_library(table, FP_TABLE_HEAD, ENTRY)
    raw = table.read_bytes().decode()
    assert "\n" not in raw.replace("\r\n", "")


def test_rejects_wrong_or_corrupt_file(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    with pytest.raises(LibraryTableError):
        ensure_library(table, FP_TABLE_HEAD, ENTRY)
    table.write_text("(fp_lib_table (lib ", encoding="utf-8")
    with pytest.raises(LibraryTableError):
        ensure_library(table, FP_TABLE_HEAD, ENTRY)


def test_empty_table_gets_entry(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    table.write_text("(fp_lib_table)", encoding="utf-8")
    ensure_library(table, FP_TABLE_HEAD, ENTRY)
    assert [e.name for e in read_entries(table, FP_TABLE_HEAD)] == ["jlc"]
