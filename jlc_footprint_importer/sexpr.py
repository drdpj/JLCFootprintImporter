# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal KiCad S-expression parser that records source offsets.

Offsets let callers edit a file by textual splicing, so everything the parser
does not touch (formatting, ordering, unknown entries) is preserved byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


class SExprError(ValueError):
    """Raised when text is not a well-formed S-expression."""


@dataclass(frozen=True)
class Atom:
    value: str
    quoted: bool
    start: int
    end: int


@dataclass
class Node:
    children: list["Item"] = field(default_factory=list)
    start: int = 0
    end: int = 0  # offset one past the closing parenthesis

    @property
    def head(self) -> str | None:
        if self.children and isinstance(self.children[0], Atom):
            return self.children[0].value
        return None

    def find_all(self, head: str) -> list["Node"]:
        return [c for c in self.children if isinstance(c, Node) and c.head == head]

    def find(self, head: str) -> "Node | None":
        found = self.find_all(head)
        return found[0] if found else None

    def atom_args(self) -> list[str]:
        """Values of the direct atom children after the head."""
        return [c.value for c in self.children[1:] if isinstance(c, Atom)]


Item = Union[Atom, Node]

_WHITESPACE = " \t\r\n"


def parse(text: str) -> Node:
    """Parse text containing exactly one top-level list."""
    pos = _skip_ws(text, 0)
    if pos >= len(text) or text[pos] != "(":
        raise SExprError("expected '(' at start of document")
    node, pos = _parse_list(text, pos)
    pos = _skip_ws(text, pos)
    if pos != len(text):
        raise SExprError(f"unexpected trailing content at offset {pos}")
    return node


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in _WHITESPACE:
        pos += 1
    return pos


def _parse_list(text: str, pos: int) -> tuple[Node, int]:
    node = Node(start=pos)
    pos += 1
    while True:
        pos = _skip_ws(text, pos)
        if pos >= len(text):
            raise SExprError("unterminated list")
        ch = text[pos]
        if ch == ")":
            node.end = pos + 1
            return node, pos + 1
        if ch == "(":
            child, pos = _parse_list(text, pos)
            node.children.append(child)
        elif ch == '"':
            atom, pos = _parse_string(text, pos)
            node.children.append(atom)
        else:
            atom, pos = _parse_bare(text, pos)
            node.children.append(atom)


def _parse_string(text: str, pos: int) -> tuple[Atom, int]:
    start = pos
    pos += 1
    out: list[str] = []
    while pos < len(text):
        ch = text[pos]
        if ch == "\\" and pos + 1 < len(text):
            nxt = text[pos + 1]
            out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
            pos += 2
        elif ch == '"':
            return Atom("".join(out), True, start, pos + 1), pos + 1
        else:
            out.append(ch)
            pos += 1
    raise SExprError("unterminated string")


def _parse_bare(text: str, pos: int) -> tuple[Atom, int]:
    start = pos
    while pos < len(text) and text[pos] not in _WHITESPACE + '()"':
        pos += 1
    return Atom(text[start:pos], False, start, pos), pos


def quote(value: str) -> str:
    """Quote a string for KiCad S-expression output."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "")
    )
    return f'"{escaped}"'
