# SPDX-License-Identifier: GPL-3.0-or-later
"""Safely register libraries in KiCad's fp-lib-table / sym-lib-table."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .sexpr import Node, SExprError, parse, quote

FP_TABLE_HEAD = "fp_lib_table"
SYM_TABLE_HEAD = "sym_lib_table"

# 7 matches the global tables KiCad 10.0.6 writes (checked on the dev machine); this is
# only used when a project has no table yet. KiCad also reads tables without a version.
NEW_TABLE_VERSION = 7


class LibraryTableError(Exception):
    """The table is unreadable or conflicts with the library we want to add."""


@dataclass(frozen=True)
class LibEntry:
    name: str
    uri: str
    type: str = "KiCad"
    options: str = ""
    descr: str = ""

    def to_sexpr(self) -> str:
        return (
            f"(lib (name {quote(self.name)})(type {quote(self.type)})"
            f"(uri {quote(self.uri)})(options {quote(self.options)})"
            f"(descr {quote(self.descr)}))"
        )


def _normalise_uri(uri: str) -> str:
    return uri.replace("\\", "/").rstrip("/").lower()


def _field(lib: Node, key: str) -> str | None:
    node = lib.find(key)
    if node is None:
        return None
    args = node.atom_args()
    return args[0] if args else ""


def read_entries(table_path: Path, head: str) -> list[LibEntry]:
    """Return the entries in an existing table (empty list if the file is absent)."""
    if not table_path.exists():
        return []
    root = _parse_table(table_path.read_bytes().decode("utf-8"), head, table_path)
    return [
        LibEntry(
            name=_field(lib, "name") or "",
            uri=_field(lib, "uri") or "",
            type=_field(lib, "type") or "",
            options=_field(lib, "options") or "",
            descr=_field(lib, "descr") or "",
        )
        for lib in root.find_all("lib")
    ]


def _parse_table(text: str, head: str, path: Path) -> Node:
    try:
        root = parse(text)
    except SExprError as exc:
        raise LibraryTableError(f"{path.name} is not valid: {exc}") from exc
    if root.head != head:
        raise LibraryTableError(f"{path.name} is not a {head} file")
    return root


def ensure_library(table_path: Path, head: str, entry: LibEntry) -> bool:
    """Add `entry` to the table unless it is already listed.

    Existing entries are never rewritten. Returns True if the file was changed.
    Raises LibraryTableError if a different library already uses the nickname.
    """
    if not table_path.exists():
        _atomic_write(
            table_path,
            f"({head}\n  (version {NEW_TABLE_VERSION})\n  {entry.to_sexpr()}\n)\n",
        )
        return True

    text = table_path.read_bytes().decode("utf-8")
    root = _parse_table(text, head, table_path)

    for lib in root.find_all("lib"):
        name = _field(lib, "name")
        uri = _field(lib, "uri") or ""
        same_uri = _normalise_uri(uri) == _normalise_uri(entry.uri)
        if name == entry.name:
            if same_uri:
                return False
            raise LibraryTableError(
                f'{table_path.name} already has a library named "{entry.name}" '
                f"pointing to {uri!r}; rename or remove it first."
            )
        if same_uri:
            return False

    newline = "\r\n" if "\r\n" in text else "\n"
    insert_at = root.children[-1].end if root.children else root.start + len(head) + 1
    new_text = (
        text[:insert_at] + f"{newline}  {entry.to_sexpr()}" + text[insert_at:]
    )
    shutil.copy2(table_path, table_path.with_name(table_path.name + ".bak"))
    _atomic_write(table_path, new_text)
    return True


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
