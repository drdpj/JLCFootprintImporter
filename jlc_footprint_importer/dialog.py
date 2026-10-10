# SPDX-License-Identifier: GPL-3.0-or-later
"""Small wxPython dialog: ask for an LCSC ID and run the import off the UI thread.

tkinter is not available in KiCad's bundled Python (verified: ``No module named
'_tkinter'``), so this uses wxPython. The plugin venv is created with
``--system-site-packages`` from KiCad's own Python, which provides ``wx``.
TODO: the IPC docs do not promise that ``wx`` is importable from plugin venvs;
this was only observed on KiCad 10.0.6 / Windows.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import wx

from .importer import ImportResult, Status, import_part

log = logging.getLogger(__name__)


class ImportDialog(wx.Dialog):
    def __init__(self, project_dir: Path, prefill: str = "") -> None:
        super().__init__(None, title="Import LCSC part", style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
        self._project_dir = project_dir

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="LCSC part number (e.g. C1002):"), 0, wx.ALL, 10)
        self._entry = wx.TextCtrl(self, value=prefill, size=(260, -1), style=wx.TE_PROCESS_ENTER)
        sizer.Add(self._entry, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)

        self._status = wx.TextCtrl(
            self,
            value=f"Library: {project_dir / 'jlc-libs'}",
            size=(460, 130),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
        )
        sizer.Add(self._status, 1, wx.ALL | wx.EXPAND, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self._import_btn = wx.Button(self, label="Import")
        self._import_btn.SetDefault()
        close_btn = wx.Button(self, wx.ID_CANCEL, label="Close")
        buttons.Add(self._import_btn, 0, wx.RIGHT, 6)
        buttons.Add(close_btn)
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizerAndFit(sizer)
        self.CentreOnScreen()
        self._import_btn.Bind(wx.EVT_BUTTON, lambda _e: self._start())
        self._entry.Bind(wx.EVT_TEXT_ENTER, lambda _e: self._start())
        self._entry.SetFocus()

    def run(self) -> None:
        self.ShowModal()

    def _set_status(self, text: str) -> None:
        self._status.SetValue(text)

    def _start(self) -> None:
        if not self._import_btn.IsEnabled():
            return
        raw = self._entry.GetValue()
        self._import_btn.Disable()
        self._set_status("Importing… (this can take a few seconds)")
        threading.Thread(target=self._worker, args=(raw,), daemon=True).start()

    def _worker(self, raw: str) -> None:
        try:
            result = import_part(self._project_dir, raw)
        except Exception:  # never show a stack trace; it goes to the log file
            log.exception("Unexpected error importing %r", raw)
            result = ImportResult(Status.FAILED, "Unexpected error. See jlc-footprint-importer.log in the project folder.")
        wx.CallAfter(self._finish, result)

    def _finish(self, result: ImportResult) -> None:
        text = result.message
        if result.warnings:
            text += "\n\nWarnings:\n- " + "\n- ".join(result.warnings)
        self._set_status(text)
        self._import_btn.Enable()


def show_dialog(project_dir: Path, prefill: str = "") -> None:
    app = wx.App(False)
    dialog = ImportDialog(project_dir, prefill)
    dialog.run()
    dialog.Destroy()
    del app
