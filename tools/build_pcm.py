# (C) Daniel Jameson 2026
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the KiCad Plugin and Content Manager (PCM) archive.

Layout (from the KiCad addon docs, "Python plugins"; the IPC runtime is selected by
`"runtime": "ipc"` in the version entry of metadata.json):

    metadata.json
    resources/icon.png
    plugins/plugin.json, requirements.txt, main.py, icons/, jlc_footprint_importer/, LICENSE, README.md

Also writes dist/metadata-repository.json: the same metadata with the download_* keys, which
belong only in the copy submitted to a package repository, never inside the archive.

Usage: python tools/build_pcm.py [--url DOWNLOAD_URL]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"

PLUGIN_FILES = ("plugin.json", "requirements.txt", "main.py", "LICENSE", "README.md")
PLUGIN_DIRS = ("icons", "jlc_footprint_importer")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)  # reproducible archives


def load_metadata() -> dict:
    return json.loads((PACKAGING / "metadata.json").read_text(encoding="utf-8"))


def archive_name(metadata: dict) -> str:
    return f"{metadata['identifier']}-{metadata['versions'][0]['version']}.zip"


def plugin_sources(root: Path = ROOT) -> list[tuple[Path, str]]:
    """(source file, path inside the archive) for everything that belongs in plugins/."""
    items: list[tuple[Path, str]] = [(root / name, f"plugins/{name}") for name in PLUGIN_FILES]
    for directory in PLUGIN_DIRS:
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                items.append((path, f"plugins/{path.relative_to(root).as_posix()}"))
    return items


def build_archive(dest: Path) -> Path:
    entries = [(PACKAGING / "metadata.json", "metadata.json")]
    icon = PACKAGING / "resources" / "icon.png"
    if icon.is_file():
        entries.append((icon, "resources/icon.png"))
    entries += plugin_sources()

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, name in entries:
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())
    return dest


def install_size(archive: Path) -> int:
    with zipfile.ZipFile(archive) as z:
        return sum(i.file_size for i in z.infolist())


def repository_metadata(archive: Path, url: str, metadata: dict | None = None) -> dict:
    metadata = json.loads(json.dumps(metadata or load_metadata()))
    version = metadata["versions"][0]
    version.update(
        download_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        download_size=archive.stat().st_size,
        download_url=url,
        install_size=install_size(archive),
    )
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="public download URL of the archive (for the repository metadata)")
    args = parser.parse_args(argv)

    metadata = load_metadata()
    archive = build_archive(DIST / archive_name(metadata))
    url = args.url or (
        f"{metadata['resources']['homepage']}/releases/download/v{metadata['versions'][0]['version']}/{archive.name}"
    )
    repo_meta = DIST / "metadata-repository.json"
    repo_meta.write_text(json.dumps(repository_metadata(archive, url, metadata), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {archive}\nwrote {repo_meta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
