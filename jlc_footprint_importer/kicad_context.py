# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Everything that talks to KiCad through kicad-python (the IPC API client)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import LCSC_PROPERTY_NAMES

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class KiCadContext:
    project_dir: Path
    prefill_lcsc_id: str = ""


def lcsc_id_from_fields(fields: dict[str, str]) -> str:
    """Pick an LCSC ID out of footprint field name/value pairs (case-insensitive names)."""
    lowered = {k.lower(): v for k, v in fields.items()}
    for name in LCSC_PROPERTY_NAMES:
        value = lowered.get(name.lower(), "").strip()
        if value:
            return value
    return ""


def _selected_footprint_fields(board) -> dict[str, str]:
    from kipy.proto.common.types import KiCadObjectType

    selection = board.get_selection(KiCadObjectType.KOT_PCB_FOOTPRINT)
    if len(selection) != 1:
        return {}
    footprint = selection[0]
    # TODO: unverified that custom fields (such as "LCSC") appear in
    # FootprintInstance.definition.texts as Field objects on a real KiCad 10 board;
    # the kicad-python source exposes Field(name, text) there but I could not confirm
    # this against a running KiCad. Failures here only lose the pre-fill.
    return {
        item.name: item.text.value
        for item in footprint.definition.texts
        if hasattr(item, "name") and hasattr(item, "text")
    }


def _open_documents(kicad, doc_type) -> tuple[list, str]:
    """Return (documents, error). Each editor may reject queries about the other's documents."""
    try:
        return list(kicad.get_open_documents(doc_type)), ""
    except Exception as exc:
        log.exception("get_open_documents(%s) failed", doc_type)
        return [], f"{doc_type}: {exc}"


def connect() -> KiCadContext:
    """Connect to the running KiCad (uses KICAD_API_SOCKET/KICAD_API_TOKEN set by KiCad).

    Works from the PCB editor or the schematic editor. TODO: the docs don't say which editor
    launched the action or what GetOpenDocuments returns for the other editor's type, so every
    document type is tried and failures are collected into the error. Pre-fill from a selection
    is only done for PCB footprints (reading a selected schematic symbol's fields is unverified).
    """
    from kipy import KiCad
    from kipy.proto.common.types import DocumentType

    kicad = KiCad()
    errors: list[str] = []
    for doc_type in (DocumentType.DOCTYPE_PCB, DocumentType.DOCTYPE_SCHEMATIC):
        docs, error = _open_documents(kicad, doc_type)
        if error:
            errors.append(error)
        if not docs:
            continue
        project_dir = Path(kicad.get_project(docs[0]).path)
        prefill = ""
        if doc_type == DocumentType.DOCTYPE_PCB:
            try:
                prefill = lcsc_id_from_fields(_selected_footprint_fields(kicad.get_board()))
            except Exception:  # pre-fill is best-effort
                log.exception("Could not read LCSC field from selection")
        return KiCadContext(project_dir=project_dir, prefill_lcsc_id=prefill)

    detail = "; ".join(errors) or "KiCad reported no open documents"
    raise RuntimeError(f"no PCB or schematic is open ({detail})")