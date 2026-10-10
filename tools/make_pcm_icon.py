# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-off generator for packaging/resources/icon.png (64x64 placeholder, stdlib only)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 64
BLUE = (30, 90, 160, 255)
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)


def _pixel(x: int, y: int) -> tuple[int, int, int, int]:
    corner = 10
    cx = min(x, SIZE - 1 - x)
    cy = min(y, SIZE - 1 - y)
    if cx < corner and cy < corner and (corner - cx) ** 2 + (corner - cy) ** 2 > corner**2:
        return CLEAR
    # Downward arrow into a tray.
    in_shaft = 28 <= x <= 35 and 12 <= y <= 34
    in_head = 34 <= y <= 46 and abs(x - 31.5) <= 46 - y
    in_tray = 50 <= y <= 54 and 14 <= x <= 49
    in_tray_sides = 44 <= y <= 54 and (14 <= x <= 17 or 46 <= x <= 49)
    return WHITE if in_shaft or in_head or in_tray or in_tray_sides else BLUE


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def build_png() -> bytes:
    rows = b"".join(
        b"\x00" + b"".join(bytes(_pixel(x, y)) for x in range(SIZE)) for y in range(SIZE)
    )
    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows, 9)) + _chunk(b"IEND", b"")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "packaging" / "resources" / "icon.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_png())
    print(f"wrote {out}")
