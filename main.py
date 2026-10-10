# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point launched by KiCad for the "Import LCSC part" action (see plugin.json)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# TODO: the IPC docs do not state the working directory / sys.path KiCad uses when
# launching an entrypoint, so make the plugin directory importable explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    from jlc_footprint_importer.config import setup_logging
    from jlc_footprint_importer.kicad_context import connect

    try:
        context = connect()
    except Exception as exc:  # KiCad not reachable, no board open, ...
        print(f"JLC Footprint Importer: could not connect to KiCad: {exc}", file=sys.stderr)
        return 1

    setup_logging(context.project_dir)
    log = logging.getLogger("jlc_footprint_importer")
    try:
        from jlc_footprint_importer.dialog import show_dialog

        show_dialog(context.project_dir, context.prefill_lcsc_id)
    except Exception:
        log.exception("Dialog failed")
        print(
            "JLC Footprint Importer: the dialog failed to open "
            "(see jlc-footprint-importer.log in the project folder).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
