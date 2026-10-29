# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The upstream icon set is tracked separately: the version in parentheses is the pinned
`vscode-material-icon-theme` release from `upstream.lock.json`.

## [Unreleased]

### Fixed

- **VS Code is drawn again.** `apps`/`vscode` (plus `vscode-insiders`, `com.visualstudio.code`
  and the OSS alias) is published from the vendored Material logotype through the restored
  `mappings/apps.tsv`. With the name unmapped it fell through `Inherits` to Mint-Y's restyled
  rounded square, which is what Plank and the menu were showing.
- **The Plank Trash docklet shows a can, not a folder.** `user-trash` / `user-trash-full` are
  now Colloid rows in `mappings/colloid.tsv` (both states, 16–256 px), so the dock slot and
  the desktop trash icon match what those names mean. `folder-trash` stays Material for the
  folder literally named `trash` and for `application-x-trash`.

### Added

- **`mappings/extra.tsv` + `assets/extra/`** — curated artwork overrides that win over
  Colloid and the Material fallback. First users: `notifications` and `notification-inactive`
  (one filled amber bell) and `notification-active` (the same bell with "ringing" arcs).
  Plank's `NotificationsDockItem` chains `notification-inactive;;notification-symbolic;;…;;
  notifications`, and both former answers were near-black (`#363636` Colloid panel glyph and
  a `currentColor` symbolic SVG), i.e. invisible on a dark dock.
- `verify.py` now checks *where* a name resolves: `MUST_OWN` names (`vscode`, the two trash
  names, the three bell names) must come from this theme, not from `Inherits` — that is how
  the VS Code regression went unnoticed.

### Changed

- `verify.py`'s Colloid check asserts the *desktop name* in every size directory instead of
  assuming the file is named after the Colloid source, which no longer holds when an override
  renames the artwork (`notifications-colloid.png`).
- `mappings/apps.tsv` is documented again (curated rows only); the earlier "apps stay
  unmapped" note was too absolute.

## [1.1.0] - 2026-10-29 (upstream 5.39.0, Colloid)

### Added

- **System UI comes from Colloid.** `actions`, `status`, `devices`, `categories` and the
  system applications in `apps` are now drawn from
  [`Colloid`](https://github.com/vinceliuice/Colloid-icon-theme) instead of Google's
  `material-design-icons` and the Material file icons. Text Editor, Settings (`cs-*`),
  Files, Terminal, the Mint tools, power/session buttons, window buttons, notification and
  NetworkManager indicators, audio, printers and menu categories all use Colloid's flat
  artwork.
- `mappings/colloid.tsv` (curated, 349 rows) and the generated
  `mappings/colloid-auto.tsv` (214 rows harvested from `mappings/required.tsv`), plus the
  snapshot `mappings/colloid-index.json` and `upstream-colloid.lock.json`.
- `tools/vendor-colloid-icons.py` — indexes Colloid's `src/` artwork and its `links/` alias
  overlay, resolves every row per size directory (`16`/`22`/`24`/`32`/`scalable`), vendors
  just the referenced 577 SVGs into `assets/colloid/`, and supports `--from-required`,
  `--variant dark` and `--check`. Link resolution is path independent: a checkout with
  absolutised symlinks and a pristine clone produce byte-identical output.
- `make vendor-colloid` and `make vendor-check`; `build.py --colloid-assets` to point at
  another vendored copy.
- `devices/symbolic/` — Colloid's single-colour device icons, declared `Type=Scalable`.
- A second preview sheet (`dist/ui-preview.png` → `docs/panel-icons.png`) showing the system
  UI vocabulary.

### Changed

- **SVG rasterisation moved from the Inkscape CLI to [`resvg-py`](https://pypi.org/project/resvg-py/)**,
  managed by **uv**: `pyproject.toml` + `uv.lock` pin Pillow and resvg-py, `make build`
  runs `uv sync` first, and `--renderer {auto,resvg,inkscape}` selects the backend
  (`auto` prefers resvg, Inkscape stays as a fallback). Sub-pixel antialiasing differs from
  Inkscape by <2/255 on average; a cold build drops from 64 s to 46 s and CI no longer
  installs a 100 MB GUI application.
- Every output size is rasterised from the drawing Colloid made for it (48 px uses the 32 px
  artwork, applications above 32 px use the scalable artwork); the build batches all
  Inkscape exports into one process and the raster cache key is the artwork path, not its
  stem.
- Symbolic icons are Colloid's own `symbolic/*-symbolic.svg` (normalised to
  `fill="currentColor"`), not material glyphs recoloured by the builder.
- Coverage is measured per name across the whole theme, because GTK resolves icon names per
  size rather than per context. A name may only live in one context; the build fails on
  duplicates.
- The `apps` context now ships system applications only (73 names). Third-party file
  managers moved out of `places.tsv` into the Colloid `apps` table, which is what turns the
  Files icon from a folder into a file cabinet.
- `mimetypes.tsv` resolves `application-x-cd-image` and `application-x-executable` alone
  (`devices`/`categories` no longer duplicate them).
- Shell coverage of the live desktop: `actions` 172/181, `status` 149/152, `devices` 74/75.
- The built theme now carries `LICENSE-Colloid`; because GPL-3.0 artwork is redistributed,
  the generated icon theme as a whole is GPL-3.0 (the generator stays MIT).

### Removed

- `assets/ui/`, `tools/index-material.py`, `tools/vendor-ui-icons.py`,
  `mappings/material-index.json`, `upstream-material.lock.json` and `make vendor-ui`.
- `mappings/apps.tsv` — third-party applications (VS Code, Chrome, Blender, Steam, Figma,
  Docker, …) are not painted at all and resolve through `Adwaita,hicolor,Mint-Y` to the
  vendor icon their package installs.

## [1.0.0] - 2025-10-29 (upstream 5.39.0)

### Added

- Freedesktop icon theme `Material-Cinnamon` generated from the 906 PNG icons of
  Material Icon Theme 5.39.0.
- Five contexts at nine fixed sizes (16–256 px): `places` 341 names, `mimetypes` 978,
  `categories` 86, `apps` 35, `devices` 20 — 1460 names, 14670 PNGs, 10548 symlinks.
- MIME resolution in four passes: explicit GTK names, `/usr/share/mime/globs2` +
  extension table, regex rules, top-level fallback.
- `places` exposure for every `folder-*` icon plus the Cinnamon `start-here` menu button.
- `folder` / `folder-open` synthesised from `assets/folder-base.svg`, because the upstream
  checkout has no standalone folder icon.
- `scripts/build.py` (Pillow, optional Inkscape), `scripts/verify.py` (index.theme,
  symlinks, pixel sizes, coverage, real GTK lookup), install/uninstall helpers.
- CI on every push (build + verify) and a tag-driven release workflow that attaches
  `Material-Cinnamon-5.39.0.tar.xz`.
- Full coverage of the Mint-Y `places` (47/47) and `mimetypes` (177/177) icon names.

### Known limitations

- No monochrome `-symbolic` set (GTK falls back to the coloured icon).
- No `@2x` directories; HiDPI is served by the 256 px entry in the size chain.
- Actions, status and third-party application icons are inherited from `Inherits`.
