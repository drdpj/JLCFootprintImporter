# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Thin wrapper around easyeda2kicad.

easyeda2kicad exposes no stable programmatic API: its `main(argv)` function (in
`easyeda2kicad.__main__`) is the supported entry point and reports problems only
through the `logging` module. We call it in-process and capture its log output to
classify failures; if the package cannot be imported we fall back to
`python -m easyeda2kicad` in a subprocess.
"""

from __future__ import annotations

import contextlib
import enum
import io
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

SUBPROCESS_TIMEOUT_S = 180


class FailureKind(enum.Enum):
    NETWORK = "network"
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class Parts(enum.Enum):
    """Which easyeda2kicad outputs to produce (its --full / --symbol / --footprint flags)."""

    FULL = "--full"
    SYMBOL = "--symbol"
    FOOTPRINT = "--footprint"


@dataclass(frozen=True)
class BackendResult:
    ok: bool
    log_text: str = ""
    failure: FailureKind | None = None


class EasyedaBackend(Protocol):
    def run(
        self, lcsc_id: str, output_base: Path, custom_fields: list[str], parts: Parts = Parts.FULL
    ) -> BackendResult: ...


def build_argv(
    lcsc_id: str, output_base: Path, custom_fields: list[str], parts: Parts = Parts.FULL
) -> list[str]:
    """Equivalent of: easyeda2kicad --full --lcsc_id=<ID> --output <base> [--custom-field ...]."""
    argv = [parts.value, "--lcsc_id", lcsc_id, "--output", str(output_base)]
    if custom_fields:
        argv += ["--custom-field", *custom_fields]  # nargs="+", so keep it last
    return argv


def classify_failure(log_text: str) -> FailureKind:
    """Map easyeda2kicad's log output to a failure category.

    Based on the 1.0.1 messages; unknown output falls back to FAILED.
    """
    lowered = log_text.lower()
    if "no module named" in lowered:
        return FailureKind.UNAVAILABLE
    if "api request failed" in lowered or "urlopen error" in lowered or "timed out" in lowered:
        return FailureKind.NETWORK
    if "already exists" in lowered:
        return FailureKind.ALREADY_EXISTS
    if "failed to fetch data from easyeda api" in lowered:
        return FailureKind.NOT_FOUND
    return FailureKind.FAILED


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"[{record.levelname}] {record.getMessage()}")


class LibraryBackend:
    """Runs easyeda2kicad in-process."""

    def run(
        self, lcsc_id: str, output_base: Path, custom_fields: list[str], parts: Parts = Parts.FULL
    ) -> BackendResult:
        try:
            from easyeda2kicad.__main__ import main as easyeda_main
        except ImportError as exc:
            return BackendResult(False, f"No module named easyeda2kicad ({exc})", FailureKind.UNAVAILABLE)

        root = logging.getLogger()
        handler = _ListHandler()
        previous_level = root.level
        root.addHandler(handler)
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                code = easyeda_main(build_argv(lcsc_id, output_base, custom_fields, parts))
        except Exception as exc:  # easyeda2kicad can raise on malformed API data
            log.exception("easyeda2kicad raised")
            text = "\n".join(handler.lines + [f"[EXCEPTION] {exc!r}"])
            return BackendResult(False, text, classify_failure(text))
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)

        text = "\n".join(handler.lines)
        if code == 0:
            return BackendResult(True, text)
        return BackendResult(False, text, classify_failure(text))


class SubprocessBackend:
    """Fallback: run the `easyeda2kicad` CLI (or `python -m easyeda2kicad`) as a child process."""

    def run(
        self, lcsc_id: str, output_base: Path, custom_fields: list[str], parts: Parts = Parts.FULL
    ) -> BackendResult:
        cli = shutil.which("easyeda2kicad")
        base_cmd = [cli] if cli else [sys.executable, "-m", "easyeda2kicad"]
        cmd = [*base_cmd, *build_argv(lcsc_id, output_base, custom_fields, parts)]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=SUBPROCESS_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return BackendResult(False, "easyeda2kicad subprocess timed out", FailureKind.NETWORK)
        except OSError as exc:
            return BackendResult(False, f"could not start subprocess: {exc}", FailureKind.UNAVAILABLE)
        text = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0:
            return BackendResult(True, text)
        return BackendResult(False, text, classify_failure(text))


def default_backend() -> EasyedaBackend:
    """Prefer the library; fall back to the CLI if the package is not importable."""
    try:
        import easyeda2kicad.__main__  # noqa: F401
    except ImportError:
        log.warning("easyeda2kicad not importable; using subprocess backend")
        return SubprocessBackend()
    return LibraryBackend()
