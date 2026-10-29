# Contributing

Thanks for taking the time to improve the theme. This document covers the two things most
contributions touch: **mapping tables** and **the build pipeline**.

## Requirements

- [uv](https://docs.astral.sh/uv/) 0.5+ — creates and manages `.venv` from `pyproject.toml`
  + `uv.lock` (Pillow for PNG work, **resvg-py** for SVG rasterisation)
- Optional: Inkscape 1.x — only as a fallback renderer (`--renderer inkscape`)
- Optional: a `Colloid-icon-theme` checkout next to this repository — only needed to
  re-resolve the Colloid tables (`make vendor-colloid`)
- Optional: Node.js 20+ — only needed for `make refresh-maps`

```bash
uv sync               # .venv with Pillow + resvg-py
make build verify     # make runs `uv sync` itself
```

Use `PY=/path/to/python make build` to run the scripts with another interpreter, or
`uv run python scripts/build.py` to skip make entirely.

## Mapping tables

Everything a user sees is driven by the TSV files in `mappings/`:

| File | Columns | Purpose |
| --- | --- | --- |
| `mimetypes.tsv` | `icon-name<TAB>material-icon` | exact MIME icon names (highest priority) |
| `places.tsv` | `icon-name<TAB>material-icon` | folders, home, trash, places |
| `colloid.tsv` | `context<TAB>desktop-icon<TAB>colloid-icon` | system UI vocabulary (wins over everything) |
| `colloid-auto.tsv` | same | generated from `required.tsv` for actions/status/devices |
| `categories.tsv` | `icon-name<TAB>material-icon` | legacy fallback for menu/preferences names |
| `devices.tsv` | `icon-name<TAB>material-icon` | legacy fallback for optical media |
| `mime-rules.tsv` | `regex<TAB>material-icon` | ordered fallbacks, first match wins |
| `skips.tsv` | `name<TAB>reason` | names that must never be emitted |

Rules:

1. The right-hand side must be an existing icon: `icons/file/<name>.png`,
   `icons/folder/<name>.png`, or one of the generated `folder` / `folder-open`.
2. Keep the file sorted inside a section; comments start with `#`.
3. GTK icon names are **case sensitive** — `Thunar` and `thunar` are different entries.
4. Every new row should be justified by evidence (a real icon name from a theme or from
   `/usr/share/mime/globs2`), not by guessing.

After editing, run `make build verify` and check `dist/report.md`: new names appear in the
counts, anything the builder could not resolve lands in *missing sources*, and the *artwork
sources* table shows which providers answer each context.

### Colloid rows

`mappings/colloid.tsv` is the system UI vocabulary. Add a row, then

```bash
make vendor-colloid     # resolve + vendor the artwork, refresh colloid-auto.tsv
make vendor-check       # same result as the committed index/assets?
make build verify
```

The third column is Colloid's own icon name; the vendoring step finds the drawing for every
size directory and fails on rows it cannot resolve. A `-` means "leave this name to the
legacy fallback". Third-party applications do not belong in any table — they resolve through
`hicolor` on purpose, and `verify.py` fails if their names show up in `apps/`.

## Build pipeline changes

- `scripts/build.py` — stages: extract mappings → synthesise folder icons → build context
  tables → rasterise → `index.theme` → cache → reports → archive.
- `scripts/verify.py` — the acceptance gate; new invariants belong here, not in ad-hoc
  shell checks.
- Symlinks are relative on purpose (the theme stays valid when moved). `--copy-aliases`
  exists for filesystems without symlink support.

## Pull requests

- Keep the diff focused; do not reformat unrelated code.
- Run `make build verify` (and `make verify-strict` on a Mint machine) before opening a PR.
- Mention which upstream version the change assumes.
- CI runs on Ubuntu without Mint-Y: coverage is reported there but only enforced with
  `--require-coverage`.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `chore:` …).

## Adding a whole new icon

1. Add the PNG to `icons/file` or `icons/folder` (512×512, transparent background) —
   usually by re-running `tools/convert.sh` against a newer upstream checkout.
2. Add mapping rows where the icon should be used.
3. Update `upstream.lock.json` and `CHANGELOG.md` if the upstream version changed.
