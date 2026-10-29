# Attribution

## Upstream project

The artwork in `icons/` is derived from the **Material Icon Theme** for Visual Studio Code:

- Project: <https://github.com/material-extensions/vscode-material-icon-theme>
- Pinned version: **v5.39.0** (see `upstream.lock.json`)
- Copyright: Material Extensions
- License: MIT

The upstream project ships the icons as SVG. This repository vendors 512×512 PNG
rasterisations produced with Inkscape (`tools/convert.sh`), plus a JSON snapshot of the
upstream TypeScript icon definitions (`mappings/generated-file-map.json`) from which the
extension / folder-name associations are derived.

`assets/folder-base.svg` is copied from the upstream `icons/folder-base.svg` and is used to
synthesise the plain `folder` icon and its open variant.

Upstream artwork is used for files and folders. Third-party applications (Firefox,
Thunderbird, Chrome, Blender, …) are deliberately not drawn: they fall through the
`Inherits` chain to the vendor icon their package installs into `hicolor`; see
`docs/theme-layout.md`.

The Visual Studio Code logotype the upstream set ships as `icons/vscode.png` is additionally
published as the `apps`/`vscode` icon (`mappings/apps.tsv`), i.e. the same MIT artwork reused
under its application name.

## System UI icon set (Colloid)

The desktop half of the theme — `actions`, `status`, `devices`, `categories` and the system
applications in `apps` — is derived from the **Colloid** icon theme, which is where the
Cinnamon vocabulary (`power`, `notifications`, `nm-signal-*`, `cs-*`, `xsi-*`, …) lives:

- Project: <https://github.com/vinceliuice/Colloid-icon-theme>
- Copyright: Vinceliuice and contributors
- Licence: **GPL-3.0**, see `assets/colloid/LICENSE`
- Vendored: 577 SVGs under `assets/colloid/`, copied from Colloid's `src/` artwork (the
  `links/` alias overlay is resolved, never copied) — `16`/`22`/`24`/`32` hand drawings plus
  the `scalable` and `symbolic` sets the tables reference
- Provenance: `mappings/colloid-index.json` (per target: Colloid source name, per-size
  artwork path, sha256) and `upstream-colloid.lock.json` (`src/index.theme` hash, file and
  icon counts, sha256 of the exact set)
- Regenerate with `make vendor-colloid`; verify with `make vendor-check`

Because GPL-3.0 artwork is redistributed here, the **built icon theme as a whole is
GPL-3.0**. The build copies `LICENSE` (MIT, generator) and `LICENSE-Colloid` (GPL-3.0,
artwork) into `dist/Material-Cinnamon/`.

## Dock bell (`assets/extra/`)

`assets/extra/notifications.svg` and `notification-active.svg` follow the bell and
"ringing bell" glyphs of **Material Design Icons**, re-filled in the theme's amber so the
Plank docklet stays legible on a dark dock:

- Project: <https://github.com/google/material-design-icons>
- Copyright: Google LLC
- Licence: **Apache-2.0**

## This project

- Theme generator, mapping tables, documentation and CI: MIT, see `LICENSE`.
- The generator's own code stays MIT; the generated theme bundles GPL-3.0 artwork, so the
  distributed theme is GPL-3.0.

## Trademarks

Cinnamon and Linux Mint are trademarks of the Linux Mint project; One Commander is a
product of its respective owner; Material Design is a design language by Google.
This project is not affiliated with, endorsed by, or sponsored by any of them.
