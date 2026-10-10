# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provenance properties (LCSC ID, source, import date) for imported parts."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from .config import PROP_IMPORT_DATE, PROP_LCSC, PROP_SOURCE, SOURCE_TEXT
from .partinfo import PartInfo
from .sexpr import parse, quote


@dataclass(frozen=True)
class Provenance:
    lcsc_id: str
    source: str = SOURCE_TEXT
    import_date: str = ""

    @staticmethod
    def now(lcsc_id: str, today: dt.date | None = None) -> "Provenance":
        return Provenance(lcsc_id, import_date=(today or dt.date.today()).isoformat())

    def properties(self) -> dict[str, str]:
        return {
            PROP_LCSC: self.lcsc_id,
            PROP_SOURCE: self.source,
            PROP_IMPORT_DATE: self.import_date,
        }

    def easyeda_custom_fields(self) -> list[str]:
        """KEY:VALUE arguments for easyeda2kicad's --custom-field (applied to symbols)."""
        return [f"{key}:{value}" for key, value in self.properties().items()]


def add_footprint_properties(text: str, prov: Provenance) -> str:
    """Return footprint text with provenance properties added.

    Properties that already exist (by name) are left untouched, so the operation
    is idempotent.

    TODO: the plain `(property "Key" "Value")` form is what easyeda2kicad itself
    emits for "LCSC Part"; verify in KiCad 10 that it loads them as custom fields.
    """
    return _add_missing_properties(text, prov.properties())


def _add_missing_properties(text: str, wanted: dict[str, str]) -> str:
    root = parse(text)
    existing = {
        node.atom_args()[0]
        for node in root.find_all("property")
        if node.atom_args()
    }
    missing = [(k, v) for k, v in wanted.items() if k not in existing]
    if not missing:
        return text

    properties = root.find_all("property")
    if properties:
        insert_at = properties[-1].end
    elif len(root.children) >= 2:
        insert_at = root.children[1].end  # after the footprint name
    else:
        raise ValueError("footprint has no name")

    newline = "\r\n" if "\r\n" in text else "\n"
    addition = "".join(
        f"{newline}\t(property {quote(k)} {quote(v)})" for k, v in missing
    )
    return text[:insert_at] + addition + text[insert_at:]


def apply_part_info_to_footprint(text: str, info: PartInfo) -> str:
    """Replace the footprint description/tags and add category, manufacturer and MPN properties."""
    text = _add_missing_properties(text, info.extra_properties())
    root = parse(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    descr = root.find("descr")
    tags = root.find("tags")

    edits: list[tuple[int, int, str]] = []
    if descr is not None:
        edits.append((descr.start, descr.end, f"(descr {quote(info.description)})"))
    insert_tags_at: int | None = None
    if tags is not None:
        edits.append((tags.start, tags.end, f"(tags {quote(info.keywords)})"))
    elif descr is not None:
        insert_tags_at = descr.end
    if descr is None:
        if len(root.children) < 2:
            raise ValueError("footprint has no name")
        edits.append((root.children[1].end, root.children[1].end, f"{newline}\t(descr {quote(info.description)})"))
        if tags is None:
            edits.append((root.children[1].end, root.children[1].end, f"{newline}\t(tags {quote(info.keywords)})"))
    elif insert_tags_at is not None:
        edits.append((insert_tags_at, insert_tags_at, f"{newline}\t(tags {quote(info.keywords)})"))

    for start, end, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        text = text[:start] + new + text[end:]
    return text


def apply_part_info_to_symbol_library(text: str, lcsc_id: str, info: PartInfo) -> str:
    """Set ki_description / ki_keywords on the symbol whose "LCSC Part" is lcsc_id."""
    root = parse(text)
    for symbol in root.find_all("symbol"):
        props = {
            p.atom_args()[0]: p
            for p in symbol.find_all("property")
            if len(p.atom_args()) >= 2
        }
        lcsc = props.get("LCSC Part") or props.get("LCSC")
        if lcsc is None or lcsc.atom_args()[1] != lcsc_id:
            continue
        edits = []
        for key, value in (("ki_description", info.description), ("ki_keywords", info.keywords)):
            node = props.get(key)
            if node is not None:
                value_atom = node.children[2]
                edits.append((value_atom.start, value_atom.end, quote(value)))
        for start, end, new in sorted(edits, reverse=True):
            text = text[:start] + new + text[end:]
        return text
    return text


def set_symbol_footprint(text: str, lcsc_id: str, footprint_id: str) -> str:
    """Point the "Footprint" field of the symbol carrying ``lcsc_id`` at ``footprint_id``."""
    root = parse(text)
    for symbol in root.find_all("symbol"):
        props = {
            p.atom_args()[0]: p
            for p in symbol.find_all("property")
            if len(p.atom_args()) >= 2
        }
        lcsc = props.get("LCSC Part") or props.get("LCSC")
        footprint = props.get("Footprint")
        if lcsc is None or footprint is None or lcsc.atom_args()[1] != lcsc_id:
            continue
        value = footprint.children[2]
        return text[: value.start] + quote(footprint_id) + text[value.end :]
    return text


def use_project_relative_model_path(text: str, model_dir: Path, model_uri: str) -> str:
    """Replace the absolute 3D model directory easyeda2kicad wrote with a ${KIPRJMOD} URI."""
    return text.replace(model_dir.as_posix(), model_uri)
