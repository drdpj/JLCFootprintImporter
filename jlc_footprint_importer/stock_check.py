# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface for a future "use a stock KiCad footprint if one fits" check.

Not implemented in the MVP. The intended flow, once a real checker exists:

1. The dialog asks the checker for a stock alternative *before* importing.
2. If a match is returned, the user is offered it (and the JLC import is skipped).
3. Only when `find_stock_footprint` returns None does `importer.import_part` run.

A real implementation would need part metadata (package string, category), e.g.
from the EasyEDA/LCSC product data, plus a mapping from package + category to the
stock libraries (Resistor_SMD, Capacitor_SMD, Inductor_SMD, LED_SMD, ...).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PartInfo:
    lcsc_id: str
    package: str = ""  # e.g. "0603"
    category: str = ""  # e.g. "Resistors", "Inductors"


@dataclass(frozen=True)
class StockFootprintMatch:
    lib_id: str  # e.g. "Resistor_SMD:R_0603_1608Metric"
    reason: str = ""


class StockFootprintChecker(Protocol):
    def find_stock_footprint(self, part: PartInfo) -> StockFootprintMatch | None:
        """Return a matching footprint from KiCad's standard libraries, or None."""
        ...


class NullStockFootprintChecker:
    """Default: never finds a stock footprint, so the JLC import always proceeds."""

    def find_stock_footprint(self, part: PartInfo) -> StockFootprintMatch | None:
        return None
