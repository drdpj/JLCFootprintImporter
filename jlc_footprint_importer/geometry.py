# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare the pad geometry of two footprints.

Used to tell apart "same footprint, same name" (safe to reuse) from "different
footprint that happens to have the same name" (must not be silently reused).
Only pads are compared: number, type, shape, position, size, drill and layers, all
rounded to 1 µm. Silkscreen, courtyard, text, 3D model and properties are ignored.
"""

from __future__ import annotations

from collections import Counter
from typing import NamedTuple

from .sexpr import Node, parse

_SYMMETRIC_SHAPES = {"rect", "oval", "circle"}
_MAX_REPORTED = 3


class Pad(NamedTuple):
    number: str
    kind: str
    shape: str
    x: float
    y: float
    rotation: float
    width: float
    height: float
    drill: str
    layers: tuple[str, ...]

    def describe(self) -> str:
        drill = f", drill {self.drill}" if self.drill else ""
        return (
            f"pad {self.number or '?'} ({self.kind} {self.shape}) "
            f"{self.width:g}x{self.height:g} mm at ({self.x:g}, {self.y:g}){drill}"
        )


def _numbers(node: Node | None) -> list[float]:
    values: list[float] = []
    if node is not None:
        for arg in node.atom_args():
            try:
                values.append(float(arg))
            except ValueError:
                pass
    return values


def _round(value: float) -> float:
    return round(value, 3) + 0.0  # + 0.0 turns -0.0 into 0.0


def _pad_from_node(node: Node) -> Pad:
    args = node.atom_args()
    number, kind, shape = (args + ["", "", ""])[:3]
    at = _numbers(node.find("at")) + [0.0, 0.0, 0.0]
    size = _numbers(node.find("size")) + [0.0, 0.0]
    x, y, rotation = at[0], at[1], at[2] % 360
    width, height = size[0], size[1]
    if shape in _SYMMETRIC_SHAPES:
        rotation %= 180
        if rotation == 90:
            width, height, rotation = height, width, 0
    drill_node = node.find("drill")
    drill = " ".join(drill_node.atom_args()) if drill_node is not None else ""
    layers_node = node.find("layers")
    layers = tuple(sorted(layers_node.atom_args())) if layers_node is not None else ()
    return Pad(
        number, kind, shape, _round(x), _round(y), _round(rotation), _round(width), _round(height), drill, layers
    )


def extract_pads(footprint_text: str) -> list[Pad]:
    """Raises SExprError if the text is not a well-formed S-expression."""
    return [_pad_from_node(n) for n in parse(footprint_text).find_all("pad")]


def compare_footprints(existing_text: str, new_text: str) -> list[str]:
    """Human-readable pad differences; an empty list means the pad geometry is identical."""
    existing, new = extract_pads(existing_text), extract_pads(new_text)
    differences: list[str] = []
    if len(existing) != len(new):
        differences.append(f"pad count differs ({len(existing)} in the library, {len(new)} in the new part)")
    only_existing = Counter(existing) - Counter(new)
    only_new = Counter(new) - Counter(existing)
    for pad in sorted(only_existing)[:_MAX_REPORTED]:
        differences.append(f"library has {pad.describe()}")
    for pad in sorted(only_new)[:_MAX_REPORTED]:
        differences.append(f"new part has {pad.describe()}")
    return differences
