# Theme layout

```
Material-Cinnamon/
├── index.theme
├── icon-theme.cache
├── LICENSE                        # MIT (generator)
├── LICENSE-Colloid                # GPL-3.0 (Colloid artwork)
├── places/{16,22,24,32,48,64,96,128,256}/
├── mimetypes/{…}/
├── apps/{…}/                      # system applications (Colloid)
├── categories/{…}/                # menu + preferences categories (Colloid)
├── devices/{16,22,24,32,48,64,96,128,256}/
├── actions/{16,22,24,32,48}/
├── status/{16,22,24,32,48}/
└── actions|status|devices/symbolic/   # scalable single-colour SVG
```

## `index.theme`

```ini
[Icon Theme]
Name=Material-Cinnamon
Comment=Material Design file and folder icons for Cinnamon (generated from … 5.39.0)
Inherits=Adwaita,hicolor,Mint-Y
Example=folder
Hidden=false
Directories=places/16,…,devices/48,devices/64,…,status/48,status/symbolic

[places/16]
Size=16
Context=Places
Type=Fixed

[status/symbolic]
Size=16
MinSize=1
MaxSize=512
Context=Status
Type=Scalable
```

- **Inherits** is a fixed chain (`DEFAULT_INHERIT` in `build.py`), not derived from the
  active desktop theme. `Adwaita` and `hicolor` come first so names this theme does not ship
  resolve to the vendor artwork in `hicolor` (Firefox, Thunderbird, third-party apps) rather
  than to a Mint restyling; `Mint-Y` is last and only answers what neither of the first two
  knows — the shell's own action/status/applet icons. Override with
  `--inherit hicolor,Mint-Y` (or any other order).
- Every directory is declared and carries `Size`, `Context` and `Type`. `Type=Fixed` keeps
  GTK from stretching a 48 px icon to 96 px unless a larger entry is missing.
- `Example=folder` is what icon-theme pickers show as a thumbnail.
- `actions` and `status` stop at 48 px (toolbar/panel sizes); every other context runs to
  256 px. `CTX_SIZES` in `build.py` holds that table.
- `<ctx>/symbolic/` is **scalable**, not fixed: GTK loads these SVGs to colourise the
  `*-symbolic` names, so they carry `MinSize`/`MaxSize` instead of a `Type=Fixed` section.
  `actions`, `status` and `devices` have one; `verify.py` enforces the keys and that each
  directory actually holds SVG.

## Contexts

| Directory | Context | Contents |
| --- | --- | --- |
| `places` | `Places` | folders, XDG user dirs, home, network, `start-here` — **Material**; the two trash names come from **Colloid** |
| `mimetypes` | `MimeTypes` | one name per MIME type (`text-x-python`) plus extension-derived names — **Material** |
| `apps` | `Applications` | system applications (Text Editor, Settings `cs-*`, Files, Terminal, Mint tools) — **Colloid**; curated Material rows from `mappings/apps.tsv` (VS Code) |
| `categories` | `Categories` | menu and preferences categories — **Colloid** |
| `devices` | `Devices` | optical media, disks, printers, cameras, input, network — **Colloid**, plus `symbolic/` |
| `actions` | `Actions` | session/power, window buttons, editing/navigation, mail — **Colloid** |
| `status` | `Status` | dialogs, NetworkManager, audio, notifications, Cinnamon applets — **Colloid**, plus `symbolic/` |

Third-party applications (Firefox, Thunderbird, Chrome, Blender, …) are not drawn at all;
they resolve through `Inherits` to the vendor icon in `hicolor`. VS Code is the one curated
exception: `mappings/apps.tsv` publishes the Material `vscode` logotype the set already
ships, because without it the name falls through to Mint-Y's restyled square.

## Real files vs aliases

Each context writes **one real PNG per artwork source per size** and creates **relative
symlinks** for every additional name. In the Colloid contexts the real file is named after
the Colloid icon (`apps/48/file-manager.png`, `actions/22/system-shutdown.png`), and every
desktop name is an alias (`apps/48/system-file-manager.png → file-manager.png`,
`actions/22/xfsm-shutdown.png → system-shutdown.png`), so a mapping row can be checked by
looking at the directory listing. `places`/`mimetypes` keep the historical Material naming
(`mimetypes/python.png` + `text-x-python.png → python.png`).

Colloid draws every size separately, so a 22 px target is rasterised from Colloid's 22 px
drawing, 48 px from the 32 px drawing, and application icons above 32 px from the scalable
artwork — the build never stretches one image across the whole chain.

Aliases are relative on purpose — the theme stays valid when moved or installed under a
different prefix. On filesystems without symlinks (FAT, some Windows setups) build with
`--copy-aliases`.

Aliases are relative on purpose — the theme stays valid when moved or installed under a
different prefix. On filesystems without symlinks (FAT, some Windows setups) build with
`--copy-aliases`.

## Sizes

`16, 22, 24, 32, 48, 64, 96, 128, 256` by default. Cinnamon requests 16/22/24 for panels,
32/48 for list and icon views, 64–128 for the desktop and previews. `--sizes` accepts any
list, e.g. adding `512` for very large icon views.

No `@2x` directories are generated: GTK scales from the next entry in the chain, and the
256 px images cover HiDPI screens.

## Cache

`gtk-update-icon-cache -f` is run at the end of a build (and by `install.sh`). Without it
GTK works too, but the first lookup of every icon is a filesystem scan.

## Lookup rules GTK applies (and why names are spelled carefully)

1. `folder-symbolic` → `folder-symbolic`, then `folder` (coloured fallback).
2. `text/x-python` → `text-x-python`, then the MIME subclass (`text-x-generic`), then `text`.
3. Names are case sensitive: `macroEnabled.12` must match byte for byte.
4. Lookup is per size, not per context: a name shipped in `apps` answers a request made from
   a Places menu. That is why a name may only live in one context — `build.py` fails the
   build if two contexts emit the same name with different artwork.

That is why `mimetypes.tsv` keeps the original casing.
