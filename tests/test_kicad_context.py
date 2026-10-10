# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for finding the project from the PCB or schematic editor (KiCad client faked)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

kipy = pytest.importorskip("kipy")
from kipy.proto.common.types import DocumentType  # noqa: E402

from jlc_footprint_importer import kicad_context  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class FakeKiCad:
    docs: dict = {}

    def get_open_documents(self, doc_type):
        return self.docs.get(doc_type, [])

    def get_project(self, doc):
        return SimpleNamespace(path=doc)

    def get_board(self):
        return SimpleNamespace(get_project=lambda: SimpleNamespace(path=self.docs[DocumentType.DOCTYPE_PCB][0]))


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kipy, "KiCad", FakeKiCad)
    monkeypatch.setattr(kicad_context, "_selected_footprint_fields", lambda _b: {"LCSC": "C1002"})
    return FakeKiCad


def test_schematic_only_uses_the_schematic_project(fake) -> None:
    fake.docs = {DocumentType.DOCTYPE_SCHEMATIC: ["C:/proj/a"]}
    context = kicad_context.connect()
    assert context.project_dir == Path("C:/proj/a") and context.prefill_lcsc_id == ""


def test_pcb_is_preferred_and_prefills(fake) -> None:
    fake.docs = {DocumentType.DOCTYPE_PCB: ["C:/proj/b"], DocumentType.DOCTYPE_SCHEMATIC: ["C:/proj/a"]}
    context = kicad_context.connect()
    assert context.project_dir == Path("C:/proj/b") and context.prefill_lcsc_id == "C1002"


def test_nothing_open_raises_a_clear_error(fake) -> None:
    fake.docs = {}
    with pytest.raises(RuntimeError, match="no PCB or schematic"):
        kicad_context.connect()


def test_action_is_scoped_to_pcb_and_schematic() -> None:
    action = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["actions"][0]
    assert set(action["scopes"]) == {"pcb", "schematic"}
