# SPDX-License-Identifier: GPL-3.0-or-later
"""Orchestrates one import: cache check -> easyeda2kicad -> provenance -> table registration."""

from __future__ import annotations

import datetime as dt
import enum
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .cache import find_cached_part, find_footprint_by_name
from .config import LIB_NICKNAME, LibraryPaths
from .easyeda_backend import EasyedaBackend, FailureKind, default_backend
from .libtables import (
    FP_TABLE_HEAD,
    SYM_TABLE_HEAD,
    LibEntry,
    LibraryTableError,
    ensure_library,
)
from .partinfo import PartInfoLookup, fetch_part_info
from .provenance import (
    Provenance,
    add_footprint_properties,
    apply_part_info_to_footprint,
    apply_part_info_to_symbol_library,
    use_project_relative_model_path,
)

log = logging.getLogger(__name__)

_LCSC_RE = re.compile(r"^C\d{1,12}$")

_FAILURE_MESSAGES = {
    FailureKind.NETWORK: "Could not reach EasyEDA/LCSC. Check your internet connection and try again.",
    FailureKind.NOT_FOUND: "EasyEDA has no data for this LCSC part number. Check the ID and try again.",
    FailureKind.ALREADY_EXISTS: (
        "A footprint, symbol or 3D model with the same name already exists in the jlc library. "
        "Remove or rename the existing one in jlc-libs/ and retry."
    ),
    FailureKind.UNAVAILABLE: "The easyeda2kicad package is not available in the plugin environment.",
    FailureKind.FAILED: "easyeda2kicad failed to convert this part.",
}


class Status(enum.Enum):
    IMPORTED = "imported"
    CACHED = "cached"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass
class ImportResult:
    status: Status
    message: str
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is not Status.FAILED


def normalise_lcsc_id(raw: str) -> str | None:
    candidate = raw.strip().upper()
    return candidate if _LCSC_RE.match(candidate) else None


def _snapshot(directory: Path) -> set[Path]:
    return set(directory.glob("*.kicad_mod")) if directory.is_dir() else set()


def register_libraries(paths: LibraryPaths) -> list[str]:
    """Add the jlc libraries to the project tables; returns warnings (empty on success)."""
    warnings: list[str] = []
    jobs = (
        (paths.fp_lib_table, FP_TABLE_HEAD, LibEntry(LIB_NICKNAME, paths.footprint_uri, descr="Imported LCSC/JLCPCB footprints")),
        (paths.sym_lib_table, SYM_TABLE_HEAD, LibEntry(LIB_NICKNAME, paths.symbol_uri, descr="Imported LCSC/JLCPCB symbols")),
    )
    for table, head, entry in jobs:
        try:
            ensure_library(table, head, entry)
        except (LibraryTableError, OSError) as exc:
            log.error("Could not update %s: %s", table, exc)
            warnings.append(f"Could not update {table.name}: {exc}")
    return warnings


def import_part(
    project_dir: Path,
    raw_id: str,
    backend: EasyedaBackend | None = None,
    today: dt.date | None = None,
    part_lookup: PartInfoLookup | None = None,
) -> ImportResult:
    lookup = part_lookup or fetch_part_info
    lcsc_id = normalise_lcsc_id(raw_id)
    if lcsc_id is None:
        return ImportResult(Status.FAILED, "Enter an LCSC part number such as C1002.")

    paths = LibraryPaths(project_dir)
    log.info("Import requested for %s into %s", lcsc_id, paths.lib_root)

    try:
        paths.lib_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.exception("Cannot create %s", paths.lib_root)
        return ImportResult(Status.FAILED, f"Cannot create {paths.lib_root}: {exc}")

    cached = find_cached_part(paths, lcsc_id)
    if cached.complete:
        warnings = register_libraries(paths)
        log.info("%s already in library: %s / %s", lcsc_id, cached.footprints, cached.symbols)
        return ImportResult(
            Status.CACHED,
            f"{lcsc_id} is already in the jlc library "
            f"(footprint {cached.footprints[0]}, symbol {cached.symbols[0]}). Nothing downloaded.",
            warnings,
        )
    if cached.found_any:
        return ImportResult(
            Status.FAILED,
            f"{lcsc_id} is only partly present in the jlc library "
            f"(footprints: {list(cached.footprints)}, symbols: {list(cached.symbols)}). "
            "Remove the existing entry from jlc-libs/ and import again.",
        )

    prov = Provenance.now(lcsc_id, today)
    info = lookup(lcsc_id)
    if info is not None and info.footprint_name:
        existing = find_footprint_by_name(paths, info.footprint_name)
        if existing is not None:
            log.info("%s would reuse existing footprint %s (%s)", lcsc_id, existing.name, existing.lcsc_id)
            same_as = f" (imported as {existing.lcsc_id})" if existing.lcsc_id else ""
            return ImportResult(
                Status.DUPLICATE,
                f"Not imported: {lcsc_id} uses footprint {existing.name}, which is already in the "
                f"jlc library{same_as}. You can use that footprint with this part. "
                f"To import {lcsc_id} anyway, remove or rename {existing.name}.kicad_mod in jlc-libs/jlc.pretty first.",
            )

    before = _snapshot(paths.footprint_dir)
    backend = backend or default_backend()
    result = backend.run(lcsc_id, paths.output_base, prov.easyeda_custom_fields())
    log.info("easyeda2kicad output for %s:\n%s", lcsc_id, result.log_text)
    if not result.ok:
        kind = result.failure or FailureKind.FAILED
        return ImportResult(
            Status.FAILED,
            f"{_FAILURE_MESSAGES[kind]} Details are in {paths.log_file.name}.",
        )

    new_footprints = sorted(_snapshot(paths.footprint_dir) - before)
    if not new_footprints:
        log.error("easyeda2kicad reported success but wrote no footprint for %s", lcsc_id)
        return ImportResult(
            Status.FAILED,
            f"easyeda2kicad produced no footprint for {lcsc_id}. Details are in {paths.log_file.name}.",
        )

    warnings: list[str] = []
    if info is None:
        warnings.append("Could not look up part details; the description is the raw EasyEDA value.")
    for mod in new_footprints:
        try:
            text = mod.read_bytes().decode("utf-8")
            text = use_project_relative_model_path(text, paths.model_dir, paths.model_uri)
            text = add_footprint_properties(text, prov)
            if info is not None:
                text = apply_part_info_to_footprint(text, info)
            mod.write_text(text, encoding="utf-8", newline="")
        except (OSError, ValueError) as exc:
            log.exception("Could not add provenance to %s", mod)
            warnings.append(f"Could not add provenance to {mod.name}: {exc}")

    if info is not None and paths.symbol_file.is_file():
        try:
            sym_text = paths.symbol_file.read_bytes().decode("utf-8")
            updated = apply_part_info_to_symbol_library(sym_text, lcsc_id, info)
            if updated != sym_text:
                paths.symbol_file.write_text(updated, encoding="utf-8", newline="")
        except (OSError, ValueError) as exc:
            log.exception("Could not update symbol description in %s", paths.symbol_file)
            warnings.append(f"Could not update the symbol description: {exc}")

    warnings += register_libraries(paths)
    names = ", ".join(m.stem for m in new_footprints)
    return ImportResult(
        Status.IMPORTED,
        f"Imported {lcsc_id} (footprint {names}) into the jlc library. "
        "If it does not show up yet, reopen the project or reload the library tables.",
        warnings,
    )
