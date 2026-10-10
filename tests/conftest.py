# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures: sample library files and a fake easyeda2kicad backend (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jlc_footprint_importer.config import LibraryPaths
from jlc_footprint_importer.easyeda_backend import BackendResult, FailureKind, Parts
from jlc_footprint_importer.stock_check import NullStockFootprintChecker


TWO_PADS = (
    '\t(pad 1 smd rect (at -0.70 0.00 180.00) (size 0.800 0.864) (layers F.Cu F.Paste F.Mask))\n'
    '\t(pad 2 smd rect (at 0.70 0.00 180.00) (size 0.800 0.864) (layers F.Cu F.Paste F.Mask))\n'
)


def footprint_text(
    name: str = "R0603", lcsc: str | None = "C21190", model_dir: str = "/x/jlc.3dshapes", pads: str = TWO_PADS
) -> str:
    prop = f'\t(property "LCSC Part" "{lcsc}")\n' if lcsc else ""
    return (
        f'(module easyeda2kicad:{name} (layer F.Cu) (tedit 5DC5F6A4)\n'
        f'\t(descr "a \\"quoted\\" thing")\n'
        f'\t(fp_text reference REF** (at 0 -4) (layer F.SilkS))\n'
        f"{prop}{pads}"
        f'\t(model "{model_dir}/{name}.wrl"\n\t\t(offset (xyz 0 0 0))\n\t)\n)\n'
    )


def symbol_lib_text(symbols: dict[str, str], footprint_lib: str = "jlc") -> str:
    body = "".join(
        f'  (symbol "{name}"\n    (property "Reference" "R" (at 0 0 0))\n'
        f'    (property "Footprint" "{footprint_lib}:{name}" (at 0 0 0))\n'
        f'    (property "LCSC Part" "{lcsc}" (at 0 0 0))\n  )\n'
        for name, lcsc in symbols.items()
    )
    return f"(kicad_symbol_lib\n  (version 20241209)\n  (generator test)\n{body})\n"


class FakeBackend:
    """Mimics easyeda2kicad's file output without touching the network."""

    def __init__(
        self,
        ok: bool = True,
        failure: FailureKind | None = None,
        name: str = "R0603",
        pads: str = TWO_PADS,
    ) -> None:
        self.ok, self.failure, self.name, self.pads = ok, failure, name, pads
        self.calls: list[tuple[str, Path, list[str]]] = []
        self.parts: list[Parts] = []

    def run(
        self, lcsc_id: str, output_base: Path, custom_fields: list[str], parts: Parts = Parts.FULL
    ) -> BackendResult:
        self.calls.append((lcsc_id, output_base, custom_fields))
        self.parts.append(parts)
        if not self.ok:
            return BackendResult(False, "[ERROR] simulated", self.failure)
        paths = LibraryPaths(output_base.parent.parent)
        if parts is not Parts.SYMBOL:
            paths.footprint_dir.mkdir(parents=True, exist_ok=True)
            (paths.footprint_dir / f"{self.name}.kicad_mod").write_text(
                footprint_text(self.name, lcsc_id, paths.model_dir.as_posix(), self.pads), encoding="utf-8"
            )
        if parts is not Parts.FOOTPRINT:
            paths.symbol_file.write_text(symbol_lib_text({self.name: lcsc_id}), encoding="utf-8")
        return BackendResult(True, "[INFO] done")


@pytest.fixture(autouse=True)
def no_network_or_install_lookups(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default part lookup would use the network and the stock check the installed KiCad libraries."""
    monkeypatch.setattr("jlc_footprint_importer.importer.fetch_part_info", lambda _id: None)
    monkeypatch.setattr("jlc_footprint_importer.importer.KicadStockFootprintChecker", NullStockFootprintChecker)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path
