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

With --repo-dir it also (re)generates a self-hosted PCM repository there: repository.json,
packages.json (merging versions already listed in the directory) and resources.zip. Users add
the raw URL of repository.json under PCM > Manage Repositories. The file formats follow the
working repository https://github.com/Bouni/bouni-kicad-repository; they are not in the KiCad
developer docs. TODO: the resources.zip layout (<identifier>/icon.png) is unverified.

Usage: python tools/build_pcm.py [--url DOWNLOAD_URL] [--repo-dir DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
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


def _stamp() -> dict:
    now = datetime.now(timezone.utc)
    return {"update_time_utc": now.strftime("%Y-%m-%d %H:%M:%S"), "update_timestamp": int(now.timestamp())}


def write_repository(repo_dir: Path, package: dict, base_url: str, owner_name: str) -> None:
    """Create/refresh repository.json, packages.json and resources.zip in repo_dir."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    base_url = base_url.rstrip("/")

    packages_path = repo_dir / "packages.json"
    if packages_path.is_file():
        existing = json.loads(packages_path.read_text(encoding="utf-8"))["packages"]
        previous = [p for p in existing if p["identifier"] == package["identifier"]]
        kept = [v for v in (previous[0]["versions"] if previous else []) if v["version"] != package["versions"][0]["version"]]
        package = {**package, "versions": [package["versions"][0], *kept]}
        others = [p for p in existing if p["identifier"] != package["identifier"]]
    else:
        others = []
    packages_path.write_text(json.dumps({"packages": [*others, package]}, indent=2) + "\n", encoding="utf-8")

    resources = io.BytesIO()
    with zipfile.ZipFile(resources, "w", zipfile.ZIP_DEFLATED) as z:
        icon = PACKAGING / "resources" / "icon.png"
        if icon.is_file():
            info = zipfile.ZipInfo(f"{package['identifier']}/icon.png", FIXED_TIME)
            z.writestr(info, icon.read_bytes())
    (repo_dir / "resources.zip").write_bytes(resources.getvalue())

    repository = {
        "$schema": "https://gitlab.com/kicad/code/kicad/-/raw/master/kicad/pcm/schemas/pcm.v1.schema.json#/definitions/Repository",
        "name": f"{owner_name}'s KiCad repository",
        "maintainer": package.get("maintainer", package["author"]),
        "packages": {
            "url": f"{base_url}/packages.json",
            "sha256": hashlib.sha256(packages_path.read_bytes()).hexdigest(),
            **_stamp(),
        },
        "resources": {
            "url": f"{base_url}/resources.zip",
            "sha256": hashlib.sha256(resources.getvalue()).hexdigest(),
            **_stamp(),
        },
    }
    (repo_dir / "repository.json").write_text(json.dumps(repository, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="public download URL of the archive (for the repository metadata)")
    parser.add_argument("--repo-dir", type=Path, help="also (re)generate a self-hosted PCM repository here")
    parser.add_argument("--repo-url", help="public base URL of --repo-dir (where its files will be served)")
    args = parser.parse_args(argv)
    if args.repo_dir and not args.repo_url:
        parser.error("--repo-dir needs --repo-url")

    metadata = load_metadata()
    archive = build_archive(DIST / archive_name(metadata))
    url = args.url or (
        f"{metadata['resources']['homepage']}/releases/download/v{metadata['versions'][0]['version']}/{archive.name}"
    )
    package = repository_metadata(archive, url, metadata)
    repo_meta = DIST / "metadata-repository.json"
    repo_meta.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {archive}\nwrote {repo_meta}")
    if args.repo_dir:
        write_repository(args.repo_dir, package, args.repo_url, metadata["resources"]["homepage"].split("/")[3])
        print(f"wrote repository files in {args.repo_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
