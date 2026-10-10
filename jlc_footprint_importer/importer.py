# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Orchestrates one import.

Flow: cache check -> part lookup -> stock-footprint offer -> duplicate-footprint check
(by name, then by pad geometry) -> easyeda2kicad -> provenance -> table registration.
"""

from __future__ import annotations

import datetime as dt
import enum
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .cache import ExistingFootprint, find_cached_part, find_footprint_by_name
from .config import LIB_NICKNAME, LibraryPaths
from .easyeda_backend import BackendResult, EasyedaBackend, FailureKind, Parts, default_backend
from .geometry import compare_footprints
from .libtables import (
    FP_TABLE_HEAD,
    SYM_TABLE_HEAD,
    LibEntry,
    LibraryTableError,
    ensure_library,
)
from .partinfo import PartInfo, PartInfoLookup, fetch_part_info
from .provenance import (
    Provenance,
    add_footprint_properties,
    apply_part_info_to_footprint,
    apply_part_info_to_symbol_library,
    set_symbol_footprint,
    use_project_relative_model_path,
)
from .sexpr import SExprError
from .stock_check import KicadStockFootprintChecker, StockFootprintChecker, StockFootprintMatch

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
    DUPLICATE = "duplicate"  # same name and same pads as a footprint already in the library
    CONFLICT = "conflict"  # same name but different pads: needs the user's attention
    STOCK_AVAILABLE = "stock_available"  # nothing imported yet; the user must choose
    FAILED = "failed"


class FootprintChoice(enum.Enum):
    ASK = "ask"  # offer a stock footprint if there is one
    STOCK = "stock"  # use the stock footprint: import the symbol only
    JLC = "jlc"  # import the JLC footprint and 3D model regardless


@dataclass
class ImportResult:
    status: Status
    message: str
    warnings: list[str] = field(default_factory=list)
    stock: StockFootprintMatch | None = None

    @property
    def ok(self) -> bool:
        return self.status not in (Status.FAILED, Status.CONFLICT)


def normalise_lcsc_id(raw: str) -> str | None:
    candidate = raw.strip().upper()
    return candidate if _LCSC_RE.match(candidate) else None


def _snapshot(directory: Path) -> set[Path]:
    return set(directory.glob("*.kicad_mod")) if directory.is_dir() else set()


def register_libraries(paths: LibraryPaths, footprints: bool = True) -> list[str]:
    """Add the jlc libraries to the project tables; returns warnings (empty on success).

    With ``footprints=False`` only the symbol library is registered (stock-footprint imports
    create no jlc footprint library).
    """
    warnings: list[str] = []
    jobs = [
        (paths.sym_lib_table, SYM_TABLE_HEAD, LibEntry(LIB_NICKNAME, paths.symbol_uri, descr="Imported LCSC/JLCPCB symbols")),
    ]
    if footprints:
        jobs.insert(
            0,
            (paths.fp_lib_table, FP_TABLE_HEAD, LibEntry(LIB_NICKNAME, paths.footprint_uri, descr="Imported LCSC/JLCPCB footprints")),
        )
    for table, head, entry in jobs:
        try:
            ensure_library(table, head, entry)
        except (LibraryTableError, OSError) as exc:
            log.error("Could not update %s: %s", table, exc)
            warnings.append(f"Could not update {table.name}: {exc}")
    return warnings


def _backend_failure(result: BackendResult, paths: LibraryPaths) -> ImportResult:
    kind = result.failure or FailureKind.FAILED
    return ImportResult(
        Status.FAILED,
        f"{_FAILURE_MESSAGES[kind]} Details are in {paths.log_file.name}.",
    )


def _check_existing_footprint(
    paths: LibraryPaths,
    lcsc_id: str,
    info: PartInfo,
    existing: ExistingFootprint,
    backend: EasyedaBackend,
) -> ImportResult:
    """The footprint name is taken: decide whether it is the same footprint or a clash."""
    in_library = f"{existing.name} (imported as {existing.lcsc_id})" if existing.lcsc_id else existing.name
    differences: list[str] | None = None

    with tempfile.TemporaryDirectory(prefix="jlc-compare-") as tmp:
        tmp_paths = LibraryPaths(Path(tmp))
        tmp_paths.lib_root.mkdir(parents=True, exist_ok=True)
        fetched = backend.run(lcsc_id, tmp_paths.output_base, [], Parts.FOOTPRINT)
        new_file = tmp_paths.footprint_dir / f"{existing.name}.kicad_mod"
        if fetched.ok and new_file.is_file():
            try:
                differences = compare_footprints(
                    (paths.footprint_dir / f"{existing.name}.kicad_mod").read_text(encoding="utf-8"),
                    new_file.read_text(encoding="utf-8"),
                )
            except (OSError, UnicodeDecodeError, SExprError) as exc:
                log.warning("Could not compare footprint geometry for %s: %s", lcsc_id, exc)
        else:
            log.warning("Could not fetch %s footprint for comparison:\n%s", lcsc_id, fetched.log_text)

    if differences is None:
        return ImportResult(
            Status.DUPLICATE,
            f"Not imported: {lcsc_id} uses footprint {in_library}, which is already in the jlc library. "
            "The pad geometry could not be compared, so check that it really is the same footprint.",
        )
    if not differences:
        return ImportResult(
            Status.DUPLICATE,
            f"Not imported: {lcsc_id} uses footprint {in_library}, which is already in the jlc library "
            "with identical pads. You can use that footprint with this part.",
        )
    return ImportResult(
        Status.CONFLICT,
        f"Not imported: the footprint name {in_library} is already used in the jlc library, but the "
        f"pads of {lcsc_id} differ ({'; '.join(differences)}). Nothing was changed. Rename or remove "
        f"{existing.name}.kicad_mod in jlc-libs/jlc.pretty to import {lcsc_id}.",
    )


def _import_symbol_with_stock_footprint(
    paths: LibraryPaths,
    lcsc_id: str,
    prov: Provenance,
    info: PartInfo,
    stock: StockFootprintMatch,
    backend: EasyedaBackend,
) -> ImportResult:
    result = backend.run(lcsc_id, paths.output_base, prov.easyeda_custom_fields(), Parts.SYMBOL)
    log.info("easyeda2kicad output for %s (symbol only):\n%s", lcsc_id, result.log_text)
    if not result.ok:
        return _backend_failure(result, paths)

    warnings: list[str] = []
    try:
        text = paths.symbol_file.read_bytes().decode("utf-8")
        text = apply_part_info_to_symbol_library(text, lcsc_id, info)
        text = set_symbol_footprint(text, lcsc_id, stock.lib_id)
        paths.symbol_file.write_text(text, encoding="utf-8", newline="")
    except (OSError, ValueError, SExprError) as exc:
        log.exception("Could not update symbol for %s", lcsc_id)
        return ImportResult(Status.FAILED, f"Imported the symbol but could not set its footprint: {exc}")

    warnings += register_libraries(paths, footprints=False)
    return ImportResult(
        Status.IMPORTED,
        f"Imported the symbol for {lcsc_id} with stock footprint {stock.lib_id}. "
        "No JLC footprint or 3D model was imported. If the jlc symbol library does not show up yet, "
        "reopen the project.",
        warnings,
    )


def import_part(
    project_dir: Path,
    raw_id: str,
    backend: EasyedaBackend | None = None,
    today: dt.date | None = None,
    part_lookup: PartInfoLookup | None = None,
    stock_checker: StockFootprintChecker | None = None,
    choice: FootprintChoice = FootprintChoice.ASK,
) -> ImportResult:
    lookup = part_lookup or fetch_part_info
    checker = stock_checker or KicadStockFootprintChecker()
    lcsc_id = normalise_lcsc_id(raw_id)
    if lcsc_id is None:
        return ImportResult(Status.FAILED, "Enter an LCSC part number such as C1002.")

    paths = LibraryPaths(project_dir)
    log.info("Import requested for %s into %s (choice: %s)", lcsc_id, paths.lib_root, choice.value)

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
    if cached.uses_stock_footprint:
        warnings = register_libraries(paths, footprints=False)
        return ImportResult(
            Status.CACHED,
            f"{lcsc_id} is already in the jlc library as symbol {cached.symbols[0]} using stock footprint "
            f"{cached.symbol_footprint_refs[0]}. Nothing downloaded.",
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
    backend = backend or default_backend()

    if choice is not FootprintChoice.JLC and info is not None:
        stock = checker.find_stock_footprint(info)
        if stock is not None and choice is FootprintChoice.ASK:
            return ImportResult(
                Status.STOCK_AVAILABLE,
                f"KiCad has a stock footprint for this part: {stock.lib_id} ({stock.reason}). "
                "Stock footprints are properly licensed and reviewed, so they are preferred. "
                "Use it, or import the JLC footprint and 3D model anyway?",
                stock=stock,
            )
        if stock is not None and choice is FootprintChoice.STOCK:
            return _import_symbol_with_stock_footprint(paths, lcsc_id, prov, info, stock, backend)
    if choice is FootprintChoice.STOCK:
        return ImportResult(Status.FAILED, f"No stock footprint was found for {lcsc_id}.")

    if info is not None and info.footprint_name:
        existing = find_footprint_by_name(paths, info.footprint_name)
        if existing is not None:
            result = _check_existing_footprint(paths, lcsc_id, info, existing, backend)
            log.info("%s vs existing footprint %s: %s", lcsc_id, existing.name, result.message)
            return result

    before = _snapshot(paths.footprint_dir)
    result = backend.run(lcsc_id, paths.output_base, prov.easyeda_custom_fields())
    log.info("easyeda2kicad output for %s:\n%s", lcsc_id, result.log_text)
    if not result.ok:
        return _backend_failure(result, paths)

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
