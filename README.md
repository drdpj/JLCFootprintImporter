# JLC Footprint Importer

A KiCad 10 plugin that imports an LCSC/JLCPCB part (symbol, footprint, 3D model) into a
**project-local** library, using [easyeda2kicad](https://github.com/uPesy/easyeda2kicad.py)
for the actual EasyEDA parsing/conversion.

It uses KiCad's IPC API plugin system (not the removed SWIG `pcbnew` Action Plugin API).

## What it does

1. Adds an **Import LCSC part** action to the PCB editor and the schematic editor.
2. Asks for an LCSC part number (e.g. `C1002`). If exactly one footprint is selected and it has an
   `LCSC` (or `LCSC Part`) field, the dialog is pre-filled with it.
3. Runs the equivalent of
   `easyeda2kicad --full --lcsc_id=<ID> --output <project>/jlc-libs/jlc`
   (called as a library; falls back to the CLI/subprocess if the package can't be imported).
4. Creates, inside the project folder:
   - `jlc-libs/jlc.pretty/` – footprints
   - `jlc-libs/jlc.kicad_sym` – symbols
   - `jlc-libs/jlc.3dshapes/` – 3D models (referenced as `${KIPRJMOD}/jlc-libs/jlc.3dshapes/...`)
5. Registers `jlc` in the project's `fp-lib-table` and `sym-lib-table` (existing entries are left
   byte-for-byte untouched; nothing is duplicated; a `.bak` of the previous table is kept).
6. Stamps each imported footprint and symbol with the properties `LCSC` (the ID),
   `Source` (`easyeda2kicad / LCSC`) and `Import Date` (ISO date), and writes a descriptive
   description/keywords from the EasyEDA data, e.g. `Ferrite Beads 600Ω ±25% 100MHz, L0603
   package, Sunlord GZ1608D601TF [LCSC C1002, JLCPCB Basic Part]`, plus `Category`,
   `Manufacturer`, `MPN` and `JLCPCB Part Class` properties on the footprint.
7. If the part is already in the library, nothing is downloaded and you are told so. If a
   *different* part would produce a footprint with the same name as one already in the library
   (e.g. two different 0603 resistors both give `R0603`), nothing is imported and you are told
   which existing footprint (and LCSC ID) it matches, so you can reuse it.
8. Errors (no network, unknown ID, converter failure) are shown as plain messages in the dialog;
   details go to `jlc-footprint-importer.log` in the project folder.

## Installation (KiCad 10.0.x)

### Option A: Plugin and Content Manager (recommended)

This is a self-hosted PCM repository, not KiCad's official one. Once, in KiCad open
*Plugin and Content Manager → Manage Repositories…*, add

```
https://raw.githubusercontent.com/drdpj/JLCFootprintImporter/pcm-repository/repository.json
```

then pick that repository in the dropdown, select **JLC Footprint Importer**, *Install*, and
*Apply Pending Changes*. Updates appear the same way. Alternatively download the zip from
[Releases](https://github.com/drdpj/JLCFootprintImporter/releases) and use *Install from File…*.
(The repository branch only exists after the first tagged release; see *Packaging*.)

### Option B: manual copy

1. Copy (or symlink) this folder to the KiCad user plugin directory **as its own subfolder**
   (`plugin.json` must not sit directly in `plugins\`):
   - Windows: `C:\Users\<you>\Documents\KiCad\10.0\plugins\jlc-footprint-importer\`
   - macOS: `~/Documents/KiCad/10.0/plugins/jlc-footprint-importer/`
   - Linux: `~/.local/share/KiCad/10.0/plugins/jlc-footprint-importer/`

   Only `plugin.json`, `requirements.txt`, `main.py`, `icons/` and `jlc_footprint_importer/` are needed.
   KiCad requires the `identifier` in `plugin.json` to be reverse-DNS style with at least three
   parts (e.g. `com.github.<your-user>.jlc-footprint-importer`); change `drdpj` to your own
   GitHub username if you fork this.
2. In KiCad 10.0.6 there is an **Enable KiCad API** checkbox under Preferences → Plugins ("plugins and
   other software running on this computer can connect to KiCad"). Make sure it is ticked. It was
   ticked during all testing; I haven't tested with it off, so I don't know exactly what happens then.
3. Restart KiCad and open the PCB editor. KiCad creates a Python virtual environment for the plugin
   and installs `requirements.txt` (pinned `kicad-python` and `easyeda2kicad`). This takes a while
   and needs internet access; the toolbar button only appears once it has finished. If it never
   appears, check KiCad's trace log (see the KiCad developer docs, *IPC API → For Add-on
   Developers*), and use *Recreate Plugin Environment* from the action's context menu in the PCB
   editor preferences.

## Usage

Open a board, click **Import LCSC part**, enter the part number, press **Import**. Then add the
symbol/footprint from the `jlc` library as usual.

If KiCad has a matching stock footprint (e.g. `Resistor_SMD:R_0603_1608Metric` for an 0603
resistor), the dialog offers it first: **Use stock footprint** imports only the symbol, with its
Footprint field set to the stock footprint (no EasyEDA footprint or 3D model); **Import JLC
footprint anyway** does the full import. If the part is already in the library, nothing is
downloaded.

**The first import into a project creates the
`jlc` library entries, and KiCad only reads a project's library tables when the project is opened,
so close and reopen the project once before `jlc` shows up in the chooser.**

## Development

```
pip install -r requirements-dev.txt
python -m pytest
```

Tests mock easyeda2kicad; they never touch the network. The manifest can be checked with
`python -m kipy.packaging validate .` (from `kicad-python`).

Layout: `dialog.py` (wxPython UI), `importer.py` (orchestration), `libtables.py` + `sexpr.py` (table editing),
`provenance.py`, `partinfo.py` (descriptions/metadata), `cache.py`, `easyeda_backend.py`,
`kicad_context.py` (IPC API), `config.py` (paths/logging), `stock_check.py` (stock footprint lookup),
`geometry.py` (pad comparison).

## Packaging

`python tools/build_pcm.py` builds `dist/<identifier>-<version>.zip` (reproducible; layout per the KiCad
addon docs: `metadata.json`, `resources/icon.png`, `plugins/…`, with `"runtime": "ipc"`) and
`dist/metadata-repository.json` (the same metadata plus `download_sha256/size/url`, which belong only in a
repository entry). The version lives in `packaging/metadata.json`. Pushing a tag `vX.Y.Z` that matches
it runs `.github/workflows/release.yml`: tests, build, validate, a GitHub release with the zip, and
finally an update of the `pcm-repository` branch (`repository.json`, `packages.json` with all released
versions, `resources.zip`) that KiCad's PCM reads. To release: bump the version in
`packaging/metadata.json`, commit, `git tag vX.Y.Z`, `git push --tags`. The repository file formats are
copied from a working third-party repository (Bouni's), as the KiCad developer docs don't describe them.

## Limitations / known gaps

- **Tested on KiCad 10.0.6 / Windows only.** Verified in a running KiCad: the plugin loads, the
  toolbar action runs, the dialog opens, imports work, and the `jlc` footprint library appears
  with the imported part. Not yet verified: pre-filling from a selected footprint's `LCSC` field,
  macOS/Linux, and the symbol chooser after a reopen. Remaining `TODO` comments in the code mark
  what the docs don't specify (e.g. the working directory KiCad launches the entrypoint with).
- The dialog uses **wxPython** (`wx`), which comes from KiCad's own Python via the plugin venv
  (`--system-site-packages`). tkinter is *not* available in KiCad's bundled Python. The KiCad docs
  don't promise that `wx` is importable in plugin environments.
- The IPC API (KiCad 9/10) offers no way to refresh library tables, so the project must be
  reopened to see a newly created library.
- KiCad's console may print wxWidgets debug lines such as `TreeView_SortChildrenCB() failed` or
  `SetFocus failed`; these come from KiCad's own UI and are harmless.
- easyeda2kicad names footprints by package (e.g. `R0603`) and symbols by part number. If a part's
  footprint name already exists in the library, the new footprint is fetched to a temp folder and
  its **pads are compared** (number, type, shape, position, size, drill, layers; order and
  equivalent 0°/180° rotations are ignored):
  - identical pads → **not imported**, reported as a duplicate of the existing part;
  - different pads → **not imported**, reported as a conflict listing the differences;
  - comparison impossible (network) → treated as a duplicate with a "could not be compared" note.
  Nothing is overwritten. If the part details can't be fetched at all, this pre-check is skipped
  and easyeda2kicad's own "already exists" error applies.
- The comparison covers **pads only**. A different 3D model, silkscreen or courtyard under the same
  footprint name is not detected.
- Footprints are emitted by easyeda2kicad in its own (older-style) format; KiCad reads and
  upgrades them. Quality of EasyEDA-derived footprints and 3D models varies – always check them
  (for example, the reference text can be large and overlap the pads).
- The action is declared for both the PCB and schematic editors (`scopes` in `plugin.json`). From the
  schematic editor there is no pre-fill from a selected symbol, and the project is found from the open
  schematic. Launching from the schematic editor has been checked in KiCad 10.0.6 on Windows; the
  docs don't say which editor launched the action, so if a PCB is open it is used to find the project.
  One part per import.
- The part description is built from EasyEDA's data (category tag, value, package, manufacturer).
  It is only as good as that data.
- The toolbar icons are simple generated placeholders.
- The stock check only knows chip R/C/L/ferrite-bead/LED/diode packages (0201–2512, from the EasyEDA
  package name and reference prefix). It looks for the footprint file in KiCad's installed
  libraries; **TODO: unverified** whether KiCad exports `KICAD10_FOOTPRINT_DIR` to plugin processes
  (default install paths are the fallback). Whether a stock footprint is *electrically* right
  (e.g. a polarised or non-standard part) is your call – that's why you are asked.
- The dialog buttons for the stock choice have been run only through the importer, not clicked in a
  live KiCad.
- Installing through KiCad's PCM from this repository has been verified on KiCad 10.0.6 / Windows:
  the package installs, its icon shows in the package manager, KiCad creates the plugin's Python
  environment, and the action runs. Releases are built and published by the workflow. The plugin is
  not in KiCad's official repository.

## Licensing – please read

Copyright (C) Daniel Jameson 2026. This plugin is licensed **GPL-3.0-or-later** (see `LICENSE`). It depends on
[easyeda2kicad](https://github.com/uPesy/easyeda2kicad.py) (AGPL-3.0), installed separately via pip.

**The footprints, symbols and 3D models downloaded from EasyEDA/LCSC have no clear open licence.**
They are user-contributed or manufacturer-supplied data, and their redistribution terms are
unclear. Therefore:

- **Prefer KiCad's stock footprints** whenever one exists for the package, e.g.
  `Resistor_SMD:R_0603_1608Metric`.
- Keep imports in this **separate** library (`jlc`), do not merge them into other libraries, and
  think twice before publishing `jlc-libs/` in an open-source project. The provenance properties
  are there so imported parts stay identifiable.
