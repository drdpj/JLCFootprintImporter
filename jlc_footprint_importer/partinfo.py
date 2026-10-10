# SPDX-License-Identifier: GPL-3.0-or-later
"""Descriptive metadata (category, value, package, manufacturer) for an LCSC part.

easyeda2kicad only writes the raw value string (e.g. "600Ω ±25% 100MHz") as the
footprint description, which says nothing about what kind of part it is. This
module reads the fields of the EasyEDA component record and builds a proper
description. The lookup is best effort: failures are logged and the import goes on.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Any, Callable

log = logging.getLogger(__name__)

_TRAILING_LOCAL_NAME = re.compile(r"\s*[（(][^)）]*[)）]\s*$")


def _clean_manufacturer(name: str) -> str:
    """Drop a trailing parenthesised non-ASCII alias, e.g. 'Sunlord(顺络)' -> 'Sunlord'."""
    match = _TRAILING_LOCAL_NAME.search(name)
    if match and not match.group(0).isascii():
        return name[: match.start()].strip()
    return name.strip()


@dataclass(frozen=True)
class PartInfo:
    lcsc_id: str
    category: str = ""  # EasyEDA/LCSC product tag, e.g. "Ferrite Beads"
    value: str = ""  # LCSC description, e.g. "600Ω ±25% 100MHz"
    package: str = ""
    manufacturer: str = ""
    mpn: str = ""
    part_class: str = ""  # e.g. "Basic Part" / "Extended Part"
    footprint_name: str = ""  # name easyeda2kicad will give the footprint file

    @property
    def description(self) -> str:
        what = " ".join(p for p in (self.category, self.value) if p)
        maker = " ".join(p for p in (self.manufacturer, self.mpn) if p)
        source = f"LCSC {self.lcsc_id}" + (f", JLCPCB {self.part_class}" if self.part_class else "")
        parts = [p for p in (what, f"{self.package} package" if self.package else "", maker) if p]
        return f"{', '.join(parts)} [{source}]" if parts else f"[{source}]"

    @property
    def keywords(self) -> str:
        return " ".join(p for p in (self.category, self.package, self.manufacturer, self.mpn, self.lcsc_id) if p)

    def extra_properties(self) -> dict[str, str]:
        props = {
            "Category": self.category,
            "Manufacturer": self.manufacturer,
            "MPN": self.mpn,
            "JLCPCB Part Class": self.part_class,
        }
        return {k: v for k, v in props.items() if v}


def parse_part_info(lcsc_id: str, result: dict[str, Any]) -> PartInfo:
    """Build PartInfo from the ``result`` object of the EasyEDA component API."""
    head = (result.get("dataStr") or {}).get("head") or {}
    para = head.get("c_para") or {}
    tags = result.get("tags") or []
    package = para.get("package") or (result.get("packageDetail") or {}).get("title") or ""
    return PartInfo(
        lcsc_id=lcsc_id,
        category=str(tags[0]) if tags else "",
        value=str(result.get("description") or ""),
        package=str(package),
        manufacturer=_clean_manufacturer(str(para.get("Manufacturer") or "")),
        mpn=str(para.get("Manufacturer Part") or result.get("title") or ""),
        part_class=str(para.get("JLCPCB Part Class") or ""),
    )


PartInfoLookup = Callable[[str], "PartInfo | None"]


def fetch_part_info(lcsc_id: str) -> PartInfo | None:
    """Look the part up through easyeda2kicad's API client; None on any failure."""
    try:
        from easyeda2kicad.easyeda.easyeda_api import EasyedaApi

        result = EasyedaApi().get_cad_data_of_component(lcsc_id)
        if not result:
            return None
        info = parse_part_info(lcsc_id, result)
        try:
            from easyeda2kicad.easyeda.easyeda_importer import EasyedaFootprintImporter

            name = EasyedaFootprintImporter(easyeda_cp_cad_data=result).get_footprint().info.name
            info = replace(info, footprint_name=str(name))
        except Exception:  # the name only enables the duplicate check
            log.exception("Could not determine footprint name for %s", lcsc_id)
        return info
    except Exception:  # best effort: never block the import on metadata
        log.exception("Could not look up part info for %s", lcsc_id)
        return None
