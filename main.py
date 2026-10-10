# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point launched by KiCad for the "Import LCSC part" action (see plugin.json)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# TODO: the IPC docs do not state the working directory / sys.path KiCad uses when
# launching an entrypoint, so make the plugin directory importable explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _report_startup_failure(exc: Exception) -> None:
    """No project folder is known yet, so log to the temp folder and tell the user."""
    import tempfile
    import traceback

    log_path = Path(tempfile.gettempdir()) / "jlc-footprint-importer-startup.log"
    message = f"Could not connect to KiCad: {exc}"
    try:
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        message += f"\n\nDetails: {log_path}"
    except OSError:
        pass
    print(f"JLC Footprint Importer: {message}", file=sys.stderr)
    try:
        import wx

        app = wx.App(False)  # noqa: F841 - must exist for the message box
        wx.MessageBox(message, "JLC Footprint Importer", wx.OK | wx.ICON_ERROR)
    except Exception:
        pass


def main() -> int:
    from jlc_footprint_importer.config import setup_logging
    from jlc_footprint_importer.kicad_context import connect

    try:
        context = connect()
    except Exception as exc:  # KiCad not reachable, no board open, ...
        _report_startup_failure(exc)
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
