# Mapping tables

The generator never guesses a name twice: every icon name the theme ships comes from one of
the sources below, merged in a fixed priority order. Anything unmapped is left out and
resolved by the parent theme through `Inherits`.

## Priority (highest first)

The desktop contexts (`apps`, `categories`, `devices`, `actions`, `status`) are answered by
**Colloid** first; the legacy Material/file-icon tables only fill names the Colloid snapshot
does not know. `mimetypes` has no Colloid layer at all, and `places` only borrows two names
from it (the two trash icons), so folders stay Material.

| # | Source | File |
| --- | --- | --- |
| 1 | Curated artwork overrides | `mappings/extra.tsv` + `assets/extra/` |
| 2 | Curated Colloid rows | `mappings/colloid.tsv` |
| 3 | Generated Colloid rows (actions/status/devices) | `mappings/colloid-auto.tsv` |
| 4 | Curated Material file icons for applications | `mappings/apps.tsv` |
| 5 | Exact MIME icon names | `mappings/mimetypes.tsv` |
| 6 | MIME → extension | `/usr/share/mime/globs2`, resolved with the extension table |
| 7 | Regex fallbacks | `mappings/mime-rules.tsv` |
| 8 | Top-level fallback | built into `build.py` (`text/ → document`, …) |

The extension table itself is extracted from the upstream TypeScript definitions
(`src/core/icons/fileIcons.ts`) and committed as `mappings/generated-file-map.json`, so a
normal build needs neither Node.js nor the upstream checkout.

## `mimetypes.tsv`

```
<icon name>\t<material icon>
```

- Left side uses the GTK form: the MIME type with `/` replaced by `-`
  (`application/vnd.oasis.opendocument.text` → `application-vnd.oasis.opendocument.text`).
- Left side keeps the original casing of the MIME type. GTK lookups are case sensitive, so
  `application-vnd.ms-powerpoint.presentation.macroEnabled.12` is spelled exactly like that.
- Right side is an icon stem from `icons/` (or the generated `folder` / `folder-open`).

This table exists for the legacy/GTK-only names that no `*.ext` glob can produce, e.g.
`application-x-executable`, `text-x-python`, `application-octet-stream`,
`x-office-spreadsheet`.

## `places.tsv`

```
<place icon>\t<material icon>
```

`places` is the context Nemo, Cinnamon and the menu button use. Two kinds of entries live
here:

1. **Standard places** — `folder`, `folder-open`, `folder-drag-accept`, `user-home`,
   `user-trash`, `folder-documents`, `folder-download`, `network-workgroup`, `computer`, …
2. **Cinnamon extras** — `start-here` and `start-here-symbolic` use the Linux Mint mark
   (`mint`), which is what the menu applet requests.

The file manager *applications* (`system-file-manager`, `nemo`, `nautilus`, `thunar`, …) are
not places: they live in `mappings/colloid.tsv` under `apps` and use Colloid's file manager
artwork. A name may only be emitted from one context (GTK resolves names per size, not per
context), so keeping them out of `places.tsv` is what makes the change visible.

Two names do not come from this table any more: `user-trash` and `user-trash-full` are
Colloid rows in `mappings/colloid.tsv`. A Material `folder-trash` reads as a folder in the
48 px slot Plank's Trash docklet draws, and the desktop trash wants a can as well. The
Material `folder-trash` artwork is still used, for the folder literally named `trash` and for
`application-x-trash`.

On top of the table, `build.py` exposes every `folder-*` icon under its own name
(`folder-src`, `folder-database`, …). Disable that with `--no-extra-folder-names`.

## `mime-rules.tsv`

```
<python regex>\t<material icon>
```

Rules are evaluated top to bottom against the **raw** MIME type (`text/x-python`, not the
dashed form), first match wins, and only for names that no higher-priority source resolved.
Order matters: `java-archive` must precede the generic `java` rule, media/audio rules sit
above the `^application/` catch-alls.

## `categories.tsv` / `devices.tsv` / `ui-*.tsv` (legacy fallback)

Same two-column format (`<desktop icon name>\t<material icon>`). These tables are the
Material fallback for the desktop contexts and are now mostly empty of work: every row they
list is normally already answered by the Colloid layer. They still cover the few names Colloid
cannot express; they are read after the Colloid snapshot and never override it.

- `categories.tsv` — menu categories, preferences panels and the legacy `package_*` /
  `gnome-*` / `xfce-*` / `redhat_*` names;
- `devices.tsv` + `ui-devices.tsv` — optical media, disks, printers, cameras, input, network;
- `ui-actions.tsv`, `ui-status.tsv` — session/power, dialogs, NetworkManager, audio, applets.

## `apps.tsv`

```
<application icon name>\t<material icon>
```

Third-party applications are not redrawn by hand: a desktop entry whose logo already exists
in the vendored Material set under the same name is published under its application name
here. The current rows are VS Code (`Icon=vscode` in its `.desktop`, and `icons/vscode.png`
is the same blue ribbon) and its insiders/OSS aliases.

Without a row the name stays unmapped and resolves through `Inherits`. That is the preferred
outcome for everything else — a vendor logo from `hicolor` beats a hand-approximated brand
mark — but it also means the name can land on Mint-Y's restyled square icon, which is what
used to happen to VS Code in Plank and in the menu.

## `extra.tsv`

```
<context>\t<icon name>\t<artwork stem>
```

The highest-priority table: a name listed here is drawn from `assets/extra/<stem>.svg`,
whatever Colloid or the Material icon of that name looks like. It exists for names that need
artwork neither source has a usable version of.

The one row set today is the Plank notification bell. `NotificationsDockItem` asks for
`notification-inactive;;notification-symbolic;;…;;notifications`, so the theme has to answer
the first of those with something legible in a 48 px dock slot; Colloid's status glyph is a
`#363636` panel colour and its symbolic sibling is `currentColor`, which renders black on
Plank's dark dock. `notifications` and `notification-inactive` therefore share one filled
amber bell and `notification-active` adds the "ringing" arcs.

## `colloid.tsv` / `colloid-auto.tsv`

```
<context>\t<desktop icon name>\t<colloid icon name>
```

`colloid.tsv` is curated and wins; a `-` in the third column would mean "leave this name to
the fallback". `colloid-auto.tsv` is generated:

```bash
make vendor-colloid          # colloid.tsv + required.tsv -> colloid-auto.tsv, assets, index
make vendor-check            # compare the committed index/artwork with the checkout
```

`tools/vendor-colloid-icons.py` resolves the third column against Colloid's `src/` artwork
and `links/` alias overlay. The overlay is resolved *logically* (absolute targets are trimmed
back to the `links/` root, relative ones are joined with the link's directory), so a checkout
with absolutised symlinks and a pristine clone produce byte-identical output.

Rules of thumb:

- One row per desktop name; the icon name is Colloid's own name (`gtk-cancel` →
  `dialog-cancel`, `status-nm-signal-100-symbolic` → `nm-signal-100`).
- Cross-context resolution only trusts a hit when the resolved file is still called like the
  requested icon; `links/apps/scalable` mixes real names with historical brand aliases
  (`nm-device-wireless` → `wicd`), which are ignored.
- A target may only live in one context. The build fails with the conflicting pairs if two
  contexts emit the same name.
- `-symbolic` names use Colloid's `symbolic/*-symbolic.svg`; the name becomes an alias of the
  base icon's SVG, and GTK recolours it.
- Output sizes pick the drawing made for them: exact size directory first, then the largest
  fixed size below, then `scalable`.

## `skips.tsv`

```
<name>\t<reason>
```

Names listed here are dropped after all merging, even if a rule or the MIME database
produces them. Use it when an upstream icon looks broken at small sizes or when a name is
better served by the parent theme.

## Verification

`scripts/verify.py` checks that every name in `index.theme` exists, that aliases resolve,
that PNG dimensions match their directory, that every entry of `mappings/colloid-index.json`
reaches the built theme (real file + `symbolic` SVG), that no third-party application
artwork is shipped, and (when the reference theme is installed) that Mint-Y coverage stays at
100%. `dist/report.md` lists unresolved rows under *missing sources*, the artwork mix per
context under *artwork sources*, and every override under *name conflicts*.
