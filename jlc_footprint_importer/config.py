# SPDX-License-Identifier: GPL-3.0-or-later
"""Constants, per-project paths and file logging."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

PLUGIN_ID = "jlc-footprint-importer"

LIB_NICKNAME = "jlc"
LIB_DIR_NAME = "jlc-libs"
LOG_FILE_NAME = "jlc-footprint-importer.log"

PROJECT_VAR = "${KIPRJMOD}"

SOURCE_TEXT = "easyeda2kicad / LCSC"

# Property names written by this plugin.
PROP_LCSC = "LCSC"
PROP_SOURCE = "Source"
PROP_IMPORT_DATE = "Import Date"

# Property names that identify an LCSC part ID (easyeda2kicad itself writes "LCSC Part").
LCSC_PROPERTY_NAMES = ("LCSC", "LCSC Part")


@dataclass(frozen=True)
class LibraryPaths:
    """Locations of the project-local library, all derived from the project directory."""

    project_dir: Path

    @property
    def lib_root(self) -> Path:
        return self.project_dir / LIB_DIR_NAME

    @property
    def output_base(self) -> Path:
        """Value for easyeda2kicad's --output (it appends .pretty/.kicad_sym/.3dshapes)."""
        return self.lib_root / LIB_NICKNAME

    @property
    def footprint_dir(self) -> Path:
        return self.lib_root / f"{LIB_NICKNAME}.pretty"

    @property
    def symbol_file(self) -> Path:
        return self.lib_root / f"{LIB_NICKNAME}.kicad_sym"

    @property
    def model_dir(self) -> Path:
        return self.lib_root / f"{LIB_NICKNAME}.3dshapes"

    @property
    def fp_lib_table(self) -> Path:
        return self.project_dir / "fp-lib-table"

    @property
    def sym_lib_table(self) -> Path:
        return self.project_dir / "sym-lib-table"

    @property
    def log_file(self) -> Path:
        return self.project_dir / LOG_FILE_NAME

    @property
    def footprint_uri(self) -> str:
        return f"{PROJECT_VAR}/{LIB_DIR_NAME}/{LIB_NICKNAME}.pretty"

    @property
    def symbol_uri(self) -> str:
        return f"{PROJECT_VAR}/{LIB_DIR_NAME}/{LIB_NICKNAME}.kicad_sym"

    @property
    def model_uri(self) -> str:
        return f"{PROJECT_VAR}/{LIB_DIR_NAME}/{LIB_NICKNAME}.3dshapes"


def setup_logging(project_dir: Path) -> Path:
    """Log to <project>/jlc-footprint-importer.log; returns the log path."""
    log_path = LibraryPaths(project_dir).log_file
    logger = logging.getLogger("jlc_footprint_importer")
    logger.setLevel(logging.DEBUG)
    resolved = str(log_path.resolve())
    for handler in logger.handlers:
        if getattr(handler, "baseFilename", None) == resolved:
            return log_path
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    return log_path
