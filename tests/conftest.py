# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures: sample library files and a fake easyeda2kicad backend (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jlc_footprint_importer.config import LibraryPaths
from jlc_footprint_importer.easyeda_backend import BackendResult, FailureKind


def footprint_text(name: str = "R0603", lcsc: str | None = "C21190", model_dir: str = "/x/jlc.3dshapes") -> str:
    prop = f'\t(property "LCSC Part" "{lcsc}")\n' if lcsc else ""
    return (
        f'(module easyeda2kicad:{name} (layer F.Cu) (tedit 5DC5F6A4)\n'
        f'\t(descr "a \\"quoted\\" thing")\n'
        f'\t(fp_text reference REF** (at 0 -4) (layer F.SilkS))\n'
        f"{prop}"
        f'\t(model "{model_dir}/{name}.wrl"\n\t\t(offset (xyz 0 0 0))\n\t)\n)\n'
    )


def symbol_lib_text(symbols: dict[str, str]) -> str:
    body = "".join(
        f'  (symbol "{name}"\n    (property "Reference" "R" (at 0 0 0))\n'
        f'    (property "LCSC Part" "{lcsc}" (at 0 0 0))\n  )\n'
        for name, lcsc in symbols.items()
    )
    return f"(kicad_symbol_lib\n  (version 20241209)\n  (generator test)\n{body})\n"


class FakeBackend:
    """Mimics easyeda2kicad's file output without touching the network."""

    def __init__(self, ok: bool = True, failure: FailureKind | None = None, name: str = "R0603") -> None:
        self.ok, self.failure, self.name = ok, failure, name
        self.calls: list[tuple[str, Path, list[str]]] = []

    def run(self, lcsc_id: str, output_base: Path, custom_fields: list[str]) -> BackendResult:
        self.calls.append((lcsc_id, output_base, custom_fields))
        if not self.ok:
            return BackendResult(False, "[ERROR] simulated", self.failure)
        paths = LibraryPaths(output_base.parent.parent)
        paths.footprint_dir.mkdir(parents=True, exist_ok=True)
        (paths.footprint_dir / f"{self.name}.kicad_mod").write_text(
            footprint_text(self.name, lcsc_id, paths.model_dir.as_posix()), encoding="utf-8"
        )
        paths.symbol_file.write_text(symbol_lib_text({self.name: lcsc_id}), encoding="utf-8")
        return BackendResult(True, "[INFO] done")


@pytest.fixture(autouse=True)
def no_network_part_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default part-info lookup would use the network; tests pass their own."""
    monkeypatch.setattr("jlc_footprint_importer.importer.fetch_part_info", lambda _id: None)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path
