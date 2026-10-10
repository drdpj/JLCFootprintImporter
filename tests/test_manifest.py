# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import re
from pathlib import Path

# Copied from KiCad's API_PLUGIN::IsValidIdentifier (common/api/api_plugin.cpp), which is
# stricter than the published JSON schema.
KICAD_IDENTIFIER_RE = re.compile(
    r"^[a-zA-Z]{2,}(\.([a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]|[a-zA-Z0-9])){2,}$"
)

MANIFEST = Path(__file__).resolve().parent.parent / "plugin.json"


def test_identifier_meets_kicad_requirements() -> None:
    identifier = json.loads(MANIFEST.read_text(encoding="utf-8"))["identifier"]
    assert KICAD_IDENTIFIER_RE.match(identifier), identifier


def test_regex_rejects_plain_names() -> None:
    assert not KICAD_IDENTIFIER_RE.match("jlc-footprint-importer")
    assert not KICAD_IDENTIFIER_RE.match("com.example")


def test_entrypoint_exists() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for action in data["actions"]:
        assert (MANIFEST.parent / action["entrypoint"]).is_file()
