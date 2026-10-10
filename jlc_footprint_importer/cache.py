# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Detect whether a part is already present in the project-local library."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .config import LCSC_PROPERTY_NAMES, LibraryPaths
from .sexpr import Node, SExprError, parse

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CachedPart:
    lcsc_id: str
    footprints: tuple[str, ...] = field(default_factory=tuple)
    symbols: tuple[str, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        return bool(self.footprints) and bool(self.symbols)

    @property
    def found_any(self) -> bool:
        return bool(self.footprints) or bool(self.symbols)


@dataclass(frozen=True)
class ExistingFootprint:
    name: str
    lcsc_id: str = ""  # LCSC ID recorded in the existing footprint, if any


def _has_lcsc_property(node: Node, lcsc_id: str) -> bool:
    wanted = {name.lower() for name in LCSC_PROPERTY_NAMES}
    for prop in node.find_all("property"):
        args = prop.atom_args()
        if len(args) >= 2 and args[0].lower() in wanted and args[1].upper() == lcsc_id:
            return True
    return False


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return None


def _parse_or_none(text: str, path: Path) -> Node | None:
    try:
        return parse(text)
    except SExprError as exc:
        log.warning("Could not parse %s: %s", path, exc)
        return None


def find_footprint_by_name(paths: LibraryPaths, name: str) -> ExistingFootprint | None:
    """The footprint file easyeda2kicad would write for ``name``, if it already exists."""
    mod = paths.footprint_dir / f"{name}.kicad_mod"
    if not mod.is_file():
        return None
    lcsc_id = ""
    text = _read(mod)
    root = _parse_or_none(text, mod) if text is not None else None
    if root is not None:
        wanted = {n.lower() for n in LCSC_PROPERTY_NAMES}
        for prop in root.find_all("property"):
            args = prop.atom_args()
            if len(args) >= 2 and args[0].lower() in wanted:
                lcsc_id = args[1]
                break
    return ExistingFootprint(name, lcsc_id)


def find_cached_part(paths: LibraryPaths, lcsc_id: str) -> CachedPart:
    """Look for footprints/symbols in the jlc library carrying this LCSC ID."""
    lcsc_id = lcsc_id.upper()
    footprints: list[str] = []
    symbols: list[str] = []

    if paths.footprint_dir.is_dir():
        for mod in sorted(paths.footprint_dir.glob("*.kicad_mod")):
            text = _read(mod)
            if text is None or lcsc_id not in text.upper():
                continue
            root = _parse_or_none(text, mod)
            if root is not None and _has_lcsc_property(root, lcsc_id):
                footprints.append(mod.stem)

    if paths.symbol_file.is_file():
        text = _read(paths.symbol_file)
        if text is not None and lcsc_id in text.upper():
            root = _parse_or_none(text, paths.symbol_file)
            if root is not None:
                for sym in root.find_all("symbol"):
                    args = sym.atom_args()
                    if args and _has_lcsc_property(sym, lcsc_id):
                        symbols.append(args[0])

    return CachedPart(lcsc_id, tuple(footprints), tuple(symbols))
