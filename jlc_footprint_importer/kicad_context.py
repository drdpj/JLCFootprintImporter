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


def connect() -> KiCadContext:
    """Connect to the running KiCad (uses KICAD_API_SOCKET/KICAD_API_TOKEN set by KiCad)."""
    from kipy import KiCad

    kicad = KiCad()
    board = kicad.get_board()
    # Project.path is documented in kipy's protobuf as "The path to the project directory".
    project_dir = Path(board.get_project().path)

    prefill = ""
    try:
        prefill = lcsc_id_from_fields(_selected_footprint_fields(board))
    except Exception:  # pre-fill is best-effort
        log.exception("Could not read LCSC field from selection")
    return KiCadContext(project_dir=project_dir, prefill_lcsc_id=prefill)
