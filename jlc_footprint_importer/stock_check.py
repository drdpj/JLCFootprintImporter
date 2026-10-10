# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stock footprint check: prefer a footprint from KiCad's standard libraries.

Before importing, the part's reference prefix (R, C, L, LED, D) and imperial chip size
(e.g. 0603) are mapped to KiCad's stock naming (e.g. ``Resistor_SMD:R_0603_1608Metric``).
A match is only offered if that footprint file really exists in an installed stock
library, so nothing is suggested when the stock libraries cannot be located.

The mapping covers plain two-terminal SMD chip parts only. Everything else (connectors,
ICs, odd packages) returns no match and goes through the normal JLC import.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .partinfo import PartInfo

log = logging.getLogger(__name__)

# imperial chip size -> KiCad metric suffix (size in 0.1 mm)
_METRIC = {
    "0201": "0603Metric",
    "0402": "1005Metric",
    "0603": "1608Metric",
    "0805": "2012Metric",
    "1206": "3216Metric",
    "1210": "3225Metric",
    "1812": "4532Metric",
    "2010": "5025Metric",
    "2512": "6332Metric",
}

# reference prefix -> (stock library, footprint name prefix, kind description)
_KINDS = {
    "R": ("Resistor_SMD", "R", "resistor"),
    "C": ("Capacitor_SMD", "C", "capacitor"),
    "L": ("Inductor_SMD", "L", "inductor / ferrite bead"),
    "FB": ("Inductor_SMD", "L", "inductor / ferrite bead"),
    "LED": ("LED_SMD", "LED", "LED"),
    "D": ("Diode_SMD", "D", "diode"),
}

_PACKAGE_RE = re.compile(r"^(?:R|C|L|LED|D|FB)?(\d{4})(?:[-_ ].*)?$", re.IGNORECASE)

_ENV_VARS = ("KICAD10_FOOTPRINT_DIR", "KICAD9_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR")


@dataclass(frozen=True)
class StockFootprintMatch:
    lib_id: str  # e.g. "Resistor_SMD:R_0603_1608Metric"
    reason: str = ""


class StockFootprintChecker(Protocol):
    def find_stock_footprint(self, part: PartInfo) -> StockFootprintMatch | None:
        """Return a matching footprint from KiCad's standard libraries, or None."""
        ...


class NullStockFootprintChecker:
    """Never finds a stock footprint, so the JLC import always proceeds."""

    def find_stock_footprint(self, part: PartInfo) -> StockFootprintMatch | None:
        return None


def candidate_stock_dirs() -> list[Path]:
    """Places KiCad's stock ``*.pretty`` libraries usually live.

    TODO: the IPC API has no call that returns the stock library path (nor the
    resolved ``${KICAD10_FOOTPRINT_DIR}``), and I did not verify that KiCad exports
    these environment variables to plugin processes. So the environment is tried
    first, then the default install locations of KiCad 10 and 9.
    """
    dirs = [Path(v) for name in _ENV_VARS if (v := os.environ.get(name))]
    if sys.platform == "win32":
        for base in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"))):
            for ver in ("10.0", "9.0"):
                dirs.append(Path(base) / "KiCad" / ver / "share" / "kicad" / "footprints")
    elif sys.platform == "darwin":
        dirs.append(Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"))
    else:
        dirs += [Path("/usr/share/kicad/footprints"), Path("/usr/local/share/kicad/footprints")]
    return dirs


def guess_stock_footprint(part: PartInfo) -> tuple[str, str, str, str] | None:
    """Map a part to (library, footprint, kind, imperial size) by name only; no filesystem access."""
    match = _PACKAGE_RE.match(part.package.strip())
    if match is None or match.group(1) not in _METRIC:
        return None
    kind = _KINDS.get(part.prefix)
    if kind is None:
        return None
    library, name_prefix, description = kind
    size = match.group(1)
    return library, f"{name_prefix}_{size}_{_METRIC[size]}", description, size


class KicadStockFootprintChecker:
    def __init__(self, stock_dirs: list[Path] | None = None) -> None:
        self._dirs = stock_dirs if stock_dirs is not None else candidate_stock_dirs()

    def find_stock_footprint(self, part: PartInfo) -> StockFootprintMatch | None:
        guess = guess_stock_footprint(part)
        if guess is None:
            return None
        library, footprint, kind, size = guess
        for directory in self._dirs:
            if (directory / f"{library}.pretty" / f"{footprint}.kicad_mod").is_file():
                return StockFootprintMatch(
                    f"{library}:{footprint}",
                    f"{part.package} is a standard {size} {kind} chip package",
                )
        log.info("No stock footprint %s:%s found in %s", library, footprint, self._dirs)
        return None
