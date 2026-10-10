# (C) Daniel Jameson 2026
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

from .importer import FootprintChoice, ImportResult, Status, import_part

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
        self._stock_btn = wx.Button(self, label="Use stock footprint")
        self._jlc_btn = wx.Button(self, label="Import JLC footprint anyway")
        self._import_btn = wx.Button(self, label="Import")
        self._import_btn.SetDefault()
        close_btn = wx.Button(self, wx.ID_CANCEL, label="Close")
        buttons.Add(self._stock_btn, 0, wx.RIGHT, 6)
        buttons.Add(self._jlc_btn, 0, wx.RIGHT, 6)
        buttons.Add(self._import_btn, 0, wx.RIGHT, 6)
        buttons.Add(close_btn)
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self._pending_id = ""
        self._show_choice(False)
        self.SetSizerAndFit(sizer)
        self.CentreOnScreen()
        self._import_btn.Bind(wx.EVT_BUTTON, lambda _e: self._start())
        self._stock_btn.Bind(wx.EVT_BUTTON, lambda _e: self._start(FootprintChoice.STOCK))
        self._jlc_btn.Bind(wx.EVT_BUTTON, lambda _e: self._start(FootprintChoice.JLC))
        self._entry.Bind(wx.EVT_TEXT_ENTER, lambda _e: self._start())
        self._entry.Bind(wx.EVT_TEXT, lambda _e: self._show_choice(False))
        self._entry.SetFocus()

    def run(self) -> None:
        self.ShowModal()

    def _set_status(self, text: str) -> None:
        self._status.SetValue(text)

    def _show_choice(self, show: bool) -> None:
        """Show the stock/JLC choice buttons instead of the plain Import button."""
        self._stock_btn.Show(show)
        self._jlc_btn.Show(show)
        self._import_btn.Show(not show)
        if show:
            self._stock_btn.SetDefault()
        else:
            self._import_btn.SetDefault()
        self.Layout()

    def _start(self, choice: FootprintChoice = FootprintChoice.ASK) -> None:
        if not self._import_btn.IsEnabled():
            return
        raw = self._pending_id if choice is not FootprintChoice.ASK else self._entry.GetValue()
        self._import_btn.Disable()
        self._stock_btn.Disable()
        self._jlc_btn.Disable()
        self._set_status("Importing… (this can take a few seconds)")
        threading.Thread(target=self._worker, args=(raw, choice), daemon=True).start()

    def _worker(self, raw: str, choice: FootprintChoice) -> None:
        try:
            result = import_part(self._project_dir, raw, choice=choice)
        except Exception:  # never show a stack trace; it goes to the log file
            log.exception("Unexpected error importing %r", raw)
            result = ImportResult(Status.FAILED, "Unexpected error. See jlc-footprint-importer.log in the project folder.")
        wx.CallAfter(self._finish, raw, result)

    def _finish(self, raw: str, result: ImportResult) -> None:
        text = result.message
        if result.warnings:
            text += "\n\nWarnings:\n- " + "\n- ".join(result.warnings)
        self._set_status(text)
        self._import_btn.Enable()
        self._stock_btn.Enable()
        self._jlc_btn.Enable()
        self._pending_id = raw
        self._show_choice(result.status is Status.STOCK_AVAILABLE)


def show_dialog(project_dir: Path, prefill: str = "") -> None:
    app = wx.App(False)
    dialog = ImportDialog(project_dir, prefill)
    dialog.run()
    dialog.Destroy()
    del app
