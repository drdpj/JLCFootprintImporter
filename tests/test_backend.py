# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import sys
import types
from pathlib import Path

from jlc_footprint_importer import easyeda_backend as eb
from jlc_footprint_importer.easyeda_backend import FailureKind, LibraryBackend, build_argv, classify_failure
from jlc_footprint_importer.kicad_context import lcsc_id_from_fields


def test_argv_matches_cli_equivalent() -> None:
    argv = build_argv("C1002", Path("p/jlc-libs/jlc"), ["A:b"])
    assert argv[:4] == ["--full", "--lcsc_id", "C1002", "--output"]
    assert argv[-2:] == ["--custom-field", "A:b"]


def test_classification() -> None:
    assert classify_failure("[ERROR] API request failed: <urlopen error x>") is FailureKind.NETWORK
    assert classify_failure("[ERROR] Failed to fetch data from EasyEDA API for part C1") is FailureKind.NOT_FOUND
    assert classify_failure("[ERROR] Footprint for C1 already exists. Use --overwrite") is FailureKind.ALREADY_EXISTS
    assert classify_failure("whatever") is FailureKind.FAILED


def _fake_module(monkeypatch, main):
    pkg = types.ModuleType("easyeda2kicad")
    sub = types.ModuleType("easyeda2kicad.__main__")
    sub.main = main
    monkeypatch.setitem(sys.modules, "easyeda2kicad", pkg)
    monkeypatch.setitem(sys.modules, "easyeda2kicad.__main__", sub)


def test_library_backend_captures_logging_and_exit_code(monkeypatch) -> None:
    import logging

    def fake_main(argv):
        logging.error("Failed to fetch data from EasyEDA API for part C9")
        print("banner")
        return 1

    _fake_module(monkeypatch, fake_main)
    result = LibraryBackend().run("C9", Path("x"), [])
    assert not result.ok and result.failure is FailureKind.NOT_FOUND


def test_library_backend_converts_exceptions(monkeypatch) -> None:
    def boom(argv):
        raise RuntimeError("bad json")

    _fake_module(monkeypatch, boom)
    result = LibraryBackend().run("C9", Path("x"), [])
    assert not result.ok and result.failure is FailureKind.FAILED


def test_default_backend_falls_back_to_subprocess(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "easyeda2kicad.__main__", None)  # forces ImportError
    assert isinstance(eb.default_backend(), eb.SubprocessBackend)


def test_prefill_from_fields() -> None:
    assert lcsc_id_from_fields({"Value": "10k", "lcsc": " C25804 "}) == "C25804"
    assert lcsc_id_from_fields({"LCSC Part": "C1"}) == "C1"
    assert lcsc_id_from_fields({"Value": "x"}) == ""
