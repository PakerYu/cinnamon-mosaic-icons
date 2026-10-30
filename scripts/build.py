#!/usr/bin/env python3
"""Build the Cinnamon-Mosaic icon theme for the Cinnamon desktop.

Sources
-------
Icons come from ``icons/file/*.png`` and ``icons/folder/*.png`` (512x512 RGBA),
vendored from vscode-material-icon-theme. The extension -> icon mapping comes
from ``mappings/generated-file-map.json`` (a snapshot of the upstream
TypeScript definitions); ``--refresh-maps --upstream PATH`` regenerates it from
a checkout with Node.js installed.

Output
------
``dist/Cinnamon-Mosaic/`` — a freedesktop icon theme (places, mimetypes,
apps, categories, devices at several fixed sizes), ``index.theme``,
``icon-theme.cache`` plus reports, a preview sheet and a tar.xz archive.

Requires Pillow and an SVG rasteriser: ``resvg_py`` (installed by ``uv sync``) by
default, with the Inkscape CLI as a fallback (``--renderer inkscape``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - dependency guard
    raise SystemExit(
        "Pillow is required to build the theme.\n"
        "  python3 -m venv .venv && . .venv/bin/activate && pip install pillow\n"
        "  or: PY=/path/to/python-with-pillow make build"
    )

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
ICONS = REPO / "icons"          # vendored 512x512 PNG sources: icons/file, icons/folder
ASSETS = REPO / "assets"        # generated-icon templates (folder-base.svg)
SRC_FILE = ICONS / "file"
SRC_FOLDER = ICONS / "folder"

BUILD = REPO / "build"          # scratch (gitignored)
GEN = BUILD / "generated"
GEN_PNG = GEN / "png"
GEN_SVG = GEN / "svg"
CACHE = BUILD / "cache"
TS = BUILD / "ts"
OUT = REPO / "dist"             # gitignored build output
MAPS = REPO / "mappings"

DEFAULT_SIZES = [16, 22, 24, 32, 48, 64, 96, 128, 256]
DEFAULT_THEME = "Cinnamon-Mosaic"
# Fallback chain written into index.theme (overridable with --inherit).
# Adwaita and hicolor come first on purpose: every name this theme does not ship
# (Firefox, Thunderbird, most third-party apps) then resolves to the vendor icon
# the package installs into hicolor, instead of Mint-Y's restyled square. Mint-Y
# stays behind them only as a last resort for the action/status/applet icons the
# Cinnamon shell itself asks for.
DEFAULT_INHERIT = "Adwaita,hicolor,Mint-Y"
FOLDER_FILL = "#90a4ae"  # package.json default for material-icon-theme.folders.color

# Canonical 16x16 open folder path, taken from
# src/scripts/svg/generateOpenFolderIcons.ts so the generated variant matches
# the upstream geometry exactly.
OPEN_FOLDER_PATH = (
    "M14.483 6H4.721a1 1 0 0 0-.949.684L2 12V5h12a1 1 0 0 0-1-1H7.562a1 1 0 0 1"
    "-.64-.232l-.644-.536A1 1 0 0 0 5.638 3H2a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h11l2"
    ".403-5.606A1 1 0 0 0 14.483 6"
)

NODE_STUBS = (
    "const parseByPattern=(x)=>x;\n"
    "const IconPack=new Proxy({},{get:(_,k)=>String(k)});\n"
    "const FileNamePattern=new Proxy({},{get:(_,k)=>String(k)});\n"
)

NODE_DUMP = r"""
import fs from 'node:fs';
const file = (await import(process.argv[2])).default;
const folder = (await import(process.argv[3])).default;
const pkg = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const arr = (v) => (v || []).map(String);
const out = {
  source: pkg.name,
  version: pkg.version,
  fileIcons: file.icons.map((ic) => ({
    name: ic.name,
    extensions: arr(ic.fileExtensions),
    fileNames: arr(ic.fileNames),
    clone: ic.clone && ic.clone.base ? String(ic.clone.base) : null,
    light: !!ic.light,
    disabled: !!ic.disabled,
    enabledFor: arr(ic.enabledFor),
  })),
  folderThemes: folder.map((theme) => ({
    name: theme.name,
    defaultIcon: theme.defaultIcon ? theme.defaultIcon.name : null,
    rootFolder: theme.rootFolder ? theme.rootFolder.name : null,
    icons: (theme.icons || []).map((ic) => ({ name: ic.name, folderNames: arr(ic.folderNames) })),
  })),
};
fs.writeFileSync(process.argv[5], JSON.stringify(out, null, 1));
"""

CTX_SPEC = OrderedDict(
    [
        ("places", "Places"),
        ("mimetypes", "MimeTypes"),
        ("apps", "Applications"),
        ("categories", "Categories"),
        ("devices", "Devices"),
        ("actions", "Actions"),
        ("status", "Status"),
    ]
)

# UI contexts only need the small sizes a toolbar/panel/menu actually asks for.
CTX_SIZES: dict[str, list[int]] = {
    "actions": [16, 22, 24, 32, 48],
    "status": [16, 22, 24, 32, 48],
}

# Contexts that also get a scalable, single-colour <ctx>/symbolic/ directory so
# GTK can recolour the "*-symbolic" names Cinnamon asks for.
SYMBOLIC_CONTEXTS = ("actions", "status", "devices")

# Names Mint-Y ships for third-party applications.  The theme deliberately does
# not paint those (their vendor icons come from hicolor), so they are not counted
# as references when measuring coverage.
THIRD_PARTY_PLACES = frozenset(
    {
        "Thunar",
        "athena",
        "kfm",
        "nautilus-actions-config-tool",
        "org.xfce.filemanager",
        "org.xfce.gigolo",
        "org.xfce.thunar",
        "redhat-filemanager",
        "xfce-filemanager",
    }
)

# Contexts whose artwork is the Colloid set and whose real files are named after
# the Colloid icon (every desktop name is an alias of it).  places/mimetypes keep
# the historical Material file naming.
UI_CONTEXTS = ("apps", "categories", "devices", "actions", "status")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def sanitize(name: str) -> str:
    """Turn a MIME type or icon name into a safe icon file stem.

    Case is preserved: GTK icon lookup is case sensitive and some MIME icon
    names (``...macroEnabled.12``) and legacy place names (``Thunar``) are
    camel cased in the reference themes.
    """
    n = str(name).strip().replace("/", "-")
    n = re.sub(r"\s+", "-", n)
    n = "".join(ch for ch in n if ch.isalnum() or ch in "._+-")
    return n.strip(".-")


def tsv_rows(path: Path) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    if not path.exists():
        return rows
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) < 2:
            continue
        rows.append((sanitize(parts[0]), parts[1], lineno))
    return rows


def override_rows(path: Path) -> list[tuple[str, str, str, int]]:
    """Rows of ``mappings/extra.tsv``: ``<context>\\t<name>\\t<artwork stem>``.

    The context is its own column, so :func:`tsv_rows` (whose third element is
    the line number) cannot be reused here.
    """
    rows: list[tuple[str, str, str, int]] = []
    if not path.exists():
        return rows
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) < 3:
            continue
        rows.append((sanitize(parts[0]), sanitize(parts[1]), sanitize(parts[2]), lineno))
    return rows


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


# --------------------------------------------------------------------------- #
# stage A — extract the authoritative mapping from the TypeScript sources
# --------------------------------------------------------------------------- #
def _ts_to_mjs(src: Path, var: str) -> str:
    text = src.read_text(encoding="utf-8")
    text = re.sub(r"^import\b[\s\S]*?from\s+'[^']+';\s*", "", text, flags=re.M)
    text = re.sub(r"^(export const \w+)\s*:\s*[\w\[\]<>|. ]+?\s*=", r"\1 =", text, flags=re.M)
    return f"{NODE_STUBS}\n{text}\nexport default {var};\n"


def extract_maps(upstream: Path) -> dict | None:
    """Re-extract the mapping snapshot from a vscode-material-icon-theme checkout."""
    node = shutil.which("node")
    if not node:
        log("node not found; install Node.js or keep using the committed snapshot")
        return None
    definitions = upstream / "src/core/icons"
    if not (definitions / "fileIcons.ts").is_file():
        log(f"{upstream}: not a material-icon-theme checkout (src/core/icons missing)")
        return None
    TS.mkdir(parents=True, exist_ok=True)
    file_mjs = TS / "fileIcons.mjs"
    folder_mjs = TS / "folderIcons.mjs"
    dump_mjs = TS / "dump.mjs"
    file_mjs.write_text(_ts_to_mjs(definitions / "fileIcons.ts", "fileIcons"), encoding="utf-8")
    folder_mjs.write_text(_ts_to_mjs(definitions / "folderIcons.ts", "folderIcons"), encoding="utf-8")
    dump_mjs.write_text(NODE_DUMP, encoding="utf-8")
    target = TS / "maps.json"
    proc = subprocess.run(
        [node, str(dump_mjs), str(file_mjs), str(folder_mjs), str(upstream / "package.json"), str(target)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        log(f"node extraction failed: {proc.stderr.strip()[:400]}")
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def load_maps(refresh: bool, upstream: Path | None) -> dict:
    snapshot = MAPS / "generated-file-map.json"
    if refresh or not snapshot.exists():
        if not upstream:
            raise SystemExit(
                "--refresh-maps needs --upstream PATH pointing at a vscode-material-icon-theme checkout"
            )
        data = extract_maps(upstream)
        if data:
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(json.dumps(data, indent=1), encoding="utf-8")
            log(f"mapping snapshot refreshed: {snapshot.relative_to(REPO)}")
            return data
        if snapshot.exists():
            log("falling back to the existing mapping snapshot")
            return json.loads(snapshot.read_text(encoding="utf-8"))
        raise SystemExit("no mapping snapshot and node extraction failed")
    return json.loads(snapshot.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# stage B — generate the missing base folder icon (and its open variant)
# --------------------------------------------------------------------------- #
def _render(svg_text: str, stem: str, size: int = 512) -> Path | None:
    GEN_SVG.mkdir(parents=True, exist_ok=True)
    GEN_PNG.mkdir(parents=True, exist_ok=True)
    svg_path = GEN_SVG / f"{stem}.svg"
    png_path = GEN_PNG / f"{stem}.png"
    svg_path.write_text(svg_text, encoding="utf-8")
    try:
        render_svg(svg_path, size, png_path)
    except RenderError as exc:
        log(f"rendering {stem} failed: {exc}")
        return None
    return png_path


def generate_folder_icons(report: dict) -> dict[str, Path]:
    """Create folder.png / folder-open.png (missing from this icon checkout)."""
    made: dict[str, Path] = {}
    base_svg = ASSETS / "folder-base.svg"
    if not base_svg.exists():
        log("assets/folder-base.svg missing, cannot derive a plain folder icon")
        return made
    svg = base_svg.read_text(encoding="utf-8")
    svg_plain = re.sub(r'<path id="motive"[^>]*/>', "", svg)
    svg_plain = re.sub(r'(<path id="folder" fill=")[^"]+(")', rf"\g<1>{FOLDER_FILL}\g<2>", svg_plain)
    png = _render(svg_plain, "folder")
    if png:
        made["folder"] = png
        report["generated"].append("folder (from assets/folder-base.svg, motive path removed)")
    svg_open = re.sub(
        r'<path id="folder"[^>]*/>',
        lambda m: re.sub(r'd="[^"]*"', f'd="{OPEN_FOLDER_PATH}"', m.group(0)),
        svg_plain,
    )
    png_open = _render(svg_open, "folder-open")
    if png_open:
        made["folder-open"] = png_open
        report["generated"].append("folder-open (upstream open-folder path)")
    return made


# --------------------------------------------------------------------------- #
# stage C — icon sources
# --------------------------------------------------------------------------- #
def discover_sources(generated: dict[str, Path]) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for directory in (SRC_FILE, SRC_FOLDER):
        if not directory.is_dir():
            raise SystemExit(f"missing icon directory: {directory}")
        for png in sorted(directory.glob("*.png")):
            sources[png.stem] = png
    sources.update(generated)
    return sources


def resolve_source(
    name: str, sources: dict[str, Path], clones: dict[str, str], depth: int = 0
) -> tuple[Path | None, str | None]:
    if name in sources:
        return sources[name], None
    base = clones.get(name)
    if base and depth < 5:
        path, _ = resolve_source(base, sources, clones, depth + 1)
        if path:
            return path, base
    return None, None


# --------------------------------------------------------------------------- #
# stage C2 — artwork sources
# --------------------------------------------------------------------------- #
@dataclass
class Source:
    """One piece of artwork, plus the names that point at it.

    ``file``, ``extra`` and ``ui`` sources carry a single image that is resized
    to every output size (``extra`` is always an SVG, rendered per size).
    ``colloid`` sources carry the hand drawn artwork per Colloid
    size directory (``16``, ``22``, ``24``, ``32``, ``scalable``) and an optional
    recolourable ``symbolic`` SVG, so every target size is rendered from the
    drawing made for it.
    """

    stem: str
    provider: str  # "colloid" | "extra" | "ui" | "file"
    path: Path | None = None
    art: dict[str, Path] = field(default_factory=dict)
    symbolic: Path | None = None

    def has_fixed_art(self) -> bool:
        return bool(self.art) or self.path is not None

    def pick_art(self, size: int) -> Path | None:
        if not self.art:
            return self.path
        if str(size) in self.art:
            return self.art[str(size)]
        fixed = sorted(int(k) for k in self.art if k.isdigit())
        if "scalable" in self.art and (not fixed or size > fixed[-1]):
            return self.art["scalable"]
        if fixed:
            lower = [f for f in fixed if f <= size]
            return self.art[str(max(lower) if lower else min(fixed))]
        return self.art.get("scalable")

    def merged_with(self, other: "Source") -> "Source":
        art = dict(self.art)
        art.update({k: v for k, v in other.art.items() if k not in art})
        return Source(
            stem=self.stem,
            provider=self.provider,
            path=self.path or other.path,
            art=art,
            symbolic=self.symbolic or other.symbolic,
        )


COLLOID_ASSETS = ASSETS / "colloid"
# Curated artwork that is neither Colloid's nor a Material file icon, one SVG
# per stem, referenced by mappings/extra.tsv.
EXTRA_ASSETS = ASSETS / "extra"
# "<context>/<desktop name>" -> one entry of mappings/colloid-index.json
COLLOID: dict[str, dict] = {}


def load_colloid(index_path: Path, report: dict) -> dict[str, dict]:
    """Read the vendoring snapshot written by tools/vendor-colloid-icons.py."""
    if not index_path.exists():
        raise SystemExit(
            f"missing {index_path.relative_to(REPO)}; run `make vendor-colloid` "
            "(run `make vendor-colloid`)"
        )
    data = json.loads(index_path.read_text(encoding="utf-8"))
    icons = data.get("icons", {})
    report["colloid"] = {
        "variant": data.get("variant"),
        "source": data.get("source"),
        "icons": len(icons),
    }
    return icons


def colloid_source(meta: dict, report: dict) -> Source | None:
    art: dict[str, Path] = {}
    for size, rel in sorted(meta.get("art", {}).items()):
        path = COLLOID_ASSETS / rel
        if path.is_file():
            art[size] = path
        else:
            report["missing_sources"].append(f"colloid artwork missing: {rel}")
    symbolic = None
    rel = meta.get("symbolic")
    if rel:
        candidate = COLLOID_ASSETS / rel
        if candidate.is_file():
            symbolic = candidate
        else:
            report["missing_sources"].append(f"colloid symbol missing: {rel}")
    if not art and symbolic is None:
        return None
    return Source(stem=str(meta.get("source") or ""), provider="colloid", art=art, symbolic=symbolic)


# --------------------------------------------------------------------------- #
# stage D — build the per-context name tables
# --------------------------------------------------------------------------- #
def read_globs() -> dict[str, list[str]]:
    for candidate in ("/usr/share/mime/globs2", "/usr/share/mime/globs"):
        path = Path(candidate)
        if not path.exists():
            continue
        table: dict[str, list[str]] = defaultdict(list)
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) < 3:
                continue
            mime, glob = parts[1], parts[2]
            m = re.fullmatch(r"\*\.([A-Za-z0-9_+~.-]+)", glob)
            if m:
                table[mime].append(m.group(1).lower())
        if table:
            return dict(table)
    return {}


def build_tables(
    maps: dict,
    sources: dict[str, Path],
    clones: dict[str, str],
    args: argparse.Namespace,
    report: dict,
) -> dict[str, dict]:
    ext_map: dict[str, str] = {}
    for icon in maps["fileIcons"]:
        if icon.get("disabled"):
            continue
        for ext in icon.get("extensions", []):
            ext_map[str(ext).lower().lstrip(".")] = icon["name"]

    skips = {name for name, _reason, _ln in tsv_rows(MAPS / "skips.tsv")}

    def add_legacy(table: dict[str, Source], target: str, icon: str, where: str) -> None:
        """Material/file-icon fallback for names Colloid does not cover."""
        if not target or target in skips or target in table:
            return
        path, base = resolve_source(icon, sources, clones)
        if not path:
            report["missing_sources"].append(f"{where}:{target} -> {icon}")
            return
        if base:
            report["clone_fallbacks"][target] = f"{icon} -> {base}"
        stem = base or icon
        table[target] = Source(stem=stem, provider="file", path=path)

    def colloid_table(ctx: str) -> dict[str, Source]:
        """Every target the Colloid snapshot resolves inside one context."""
        table: dict[str, Source] = {}
        prefix = f"{ctx}/"
        for key, meta in COLLOID.items():
            if not key.startswith(prefix):
                continue
            target = key[len(prefix):]
            if target in skips:
                continue
            source = colloid_source(meta, report)
            if source is None:
                report["missing_sources"].append(f"{ctx}:{target} -> colloid:{meta.get('source')}")
                continue
            table[target] = source
        return table

    contexts: dict[str, dict] = {}

    # ---- places -----------------------------------------------------------
    # Folders, XDG dirs and trash stay Material; a Colloid row would only exist
    # here if one were added to colloid.tsv on purpose.
    places: dict[str, Source] = colloid_table("places")
    for target, icon, _ln in tsv_rows(MAPS / "places.tsv"):
        add_legacy(places, target, icon, "places")
    if not args.no_extra_folder_names:
        for name in sorted(sources):
            if (name == "folder" or name.startswith("folder-")) and name not in places:
                places[name] = Source(stem=name, provider="file", path=sources[name])
    contexts["places"] = {"context": CTX_SPEC["places"], "names": places}

    # ---- mimetypes --------------------------------------------------------
    mimes = read_globs()
    rules: list[tuple[re.Pattern[str], str]] = []
    for line in (MAPS / "mime-rules.tsv").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern, _, icon = line.partition("\t")
        pattern, icon = pattern.strip(), sanitize(icon)
        if pattern and icon:
            rules.append((re.compile(pattern), icon))

    def rule_icon(mime: str) -> str | None:
        for rx, icon in rules:
            if rx.search(mime):
                return icon
        return None

    resolved: dict[str, str] = {}
    for mime in mimes:
        icon = rule_icon(mime)
        if icon:
            resolved[sanitize(mime)] = icon
    for mime, exts in mimes.items():
        for ext in exts:
            icon = ext_map.get(ext)
            if icon:
                resolved[sanitize(mime)] = icon
                break
    exact: dict[str, str] = {}
    for target, icon, _ln in tsv_rows(MAPS / "mimetypes.tsv"):
        exact[target] = icon
        resolved[target] = icon

    mime_table: dict[str, Source] = colloid_table("mimetypes")
    for target, icon in sorted(resolved.items()):
        add_legacy(mime_table, target, icon, "mimetypes")
    contexts["mimetypes"] = {"context": CTX_SPEC["mimetypes"], "names": mime_table}
    report["mime_stats"] = {
        "system_mimes": len(mimes),
        "from_rules": sum(1 for m in mimes if rule_icon(m)),
        "exact_entries": len(exact),
        "emitted": len(mime_table),
    }

    # ---- apps / categories / devices / actions / status -------------------
    # Colloid answers these contexts.  The legacy tables stay behind it as a
    # fallback for names the Colloid snapshot does not cover (apps: the curated
    # rows in apps.tsv, i.e. only applications whose logo already exists in the
    # Material set; every other third-party app resolves through hicolor).
    for ctx, table_paths in (
        ("apps", (MAPS / "apps.tsv",)),
        ("categories", (MAPS / "categories.tsv",)),
        ("devices", (MAPS / "devices.tsv", MAPS / "ui-devices.tsv")),
        ("actions", (MAPS / "ui-actions.tsv",)),
        ("status", (MAPS / "ui-status.tsv",)),
    ):
        if ctx == "apps" and args.no_apps:
            contexts[ctx] = {"context": CTX_SPEC[ctx], "names": {}}
            continue
        table = colloid_table(ctx)
        for table_path in table_paths:
            for target, icon, _ln in tsv_rows(table_path):
                add_legacy(table, target, icon, ctx)
        contexts[ctx] = {"context": CTX_SPEC[ctx], "names": table}

    # ---- curated artwork overrides ----------------------------------------
    # Runs last, so a row in extra.tsv wins over Colloid and over the Material
    # fallback: the artwork lives in assets/extra/<stem>.svg.
    for ctx_name, target, stem, lineno in override_rows(MAPS / "extra.tsv"):
        names = contexts.get(ctx_name, {}).get("names")
        if names is None:
            report["warnings"].append(f"extra.tsv:{lineno}: unknown context {ctx_name!r}")
            continue
        artwork = EXTRA_ASSETS / f"{stem}.svg"
        if not artwork.is_file():
            report["missing_sources"].append(
                f"extra.tsv:{lineno}: {ctx_name}:{target} -> extra:{stem}.svg"
            )
            continue
        names[target] = Source(stem=stem, provider="extra", path=artwork)

    # A name may only live in one context: GTK scans directories by size, so a
    # duplicate would silently pick whichever directory came first.
    seen: dict[str, tuple[str, Source]] = {}
    duplicates: list[str] = []
    for ctx_name, ctx in contexts.items():
        for target, src in ctx["names"].items():
            previous = seen.get(target)
            if previous is not None and previous[0] != ctx_name:
                if (previous[1].provider, previous[1].stem) == (src.provider, src.stem):
                    report["notes"].append(f"{target}: same artwork in {previous[0]} and {ctx_name}")
                else:
                    duplicates.append(
                        f"{target}: {previous[0]} -> {previous[1].stem} vs {ctx_name} -> {src.stem}"
                    )
            seen.setdefault(target, (ctx_name, src))
    if duplicates:
        raise SystemExit("duplicate icon names across contexts:\n  " + "\n  ".join(sorted(duplicates)))

    return contexts


# --------------------------------------------------------------------------- #
# stage E — rasterise and lay out the theme
# --------------------------------------------------------------------------- #
class RenderError(RuntimeError):
    """An SVG could not be rasterised."""


# ``auto`` picks resvg-py when importable and falls back to the Inkscape CLI.
RENDERER = "auto"
_RENDERER: str | None = None


def svg_renderer() -> str:
    """The backend used for SVG → PNG exports ("resvg" or "inkscape")."""
    global _RENDERER
    if _RENDERER:
        return _RENDERER
    if RENDERER != "inkscape":
        try:
            import resvg_py  # noqa: F401

            _RENDERER = "resvg"
            return _RENDERER
        except ImportError:
            if RENDERER == "resvg":
                raise SystemExit(
                    "resvg-py is not installed; run `uv sync` (or `make venv`) "
                    "or pass --renderer inkscape"
                )
    if not shutil.which("inkscape"):
        raise SystemExit(
            "no SVG renderer: install resvg-py (`uv sync`) or Inkscape, "
            "or pass --renderer resvg/inkscape explicitly"
        )
    _RENDERER = "inkscape"
    return _RENDERER


def render_svg(src: Path, size: int, dest: Path) -> None:
    """Rasterise one SVG at ``size`` x ``size`` pixels.

    resvg renders the vector at the requested size, so Colloid's per-size
    drawings stay crisp; the Inkscape CLI is the fallback for machines that do
    not have the wheel.  Both write a square PNG because every icon source in
    the build is square by design.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if svg_renderer() == "resvg":
        import resvg_py

        try:
            data = resvg_py.svg_to_bytes(svg_path=str(src), width=size, height=size)
        except Exception as exc:  # noqa: BLE001 - surface the renderer message
            raise RenderError(f"{src.name}: {exc}") from exc
        dest.write_bytes(data)
        return
    proc = subprocess.run(
        [shutil.which("inkscape"), str(src), "--export-type=png",
         f"--export-filename={dest}", f"--export-width={size}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not dest.exists():
        raise RenderError(f"{src.name}: {proc.stderr.strip()[:200]}")


def cache_path(src: Path, size: int) -> Path:
    """Cache key is the artwork path and the renderer, not just its stem.

    Colloid ships one drawing per size under the same name, and switching
    between resvg and Inkscape changes the pixels, so neither may collide.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    tag = svg_renderer() if src.suffix.lower() == ".svg" else "raster"
    digest = hashlib.sha1(f"{tag}:{src}".encode("utf-8")).hexdigest()[:12]
    return CACHE / f"{digest}@{size}.png"


def _fresh(cached: Path, src: Path) -> bool:
    return cached.exists() and cached.stat().st_mtime >= src.stat().st_mtime


def rasterize_many(jobs: list[tuple[Path, int]]) -> dict[tuple[Path, int], Path]:
    """Rasterise (or resize) every unique (artwork, size) pair once."""
    cache: dict[tuple[Path, int], Path] = {}
    for src, size in dict.fromkeys(jobs):
        cached = cache_path(src, size)
        cache[(src, size)] = cached
        if _fresh(cached, src):
            continue
        if cached.exists():
            cached.unlink()
        if src.suffix.lower() == ".svg":
            render_svg(src, size, cached)
            continue
        with Image.open(src) as im:
            im = im.convert("RGBA")
            if im.size != (size, size):
                im = im.resize((size, size), Image.LANCZOS)
            im.save(cached, "PNG", optimize=True)
    return cache


def place_file(cache: Path, dest: Path) -> None:
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        os.link(cache, dest)
    except OSError:
        shutil.copy2(cache, dest)


def link_alias(dest: Path, target_name: str) -> bool:
    if dest.exists() or dest.is_symlink():
        return False
    os.symlink(f"{target_name}.png", dest)
    return True


def materialize(
    contexts: dict[str, dict],
    sizes: list[int],
    theme_dir: Path,
    args: argparse.Namespace,
    report: dict,
) -> Counter:
    stats: Counter = Counter()
    plans = []
    all_jobs: list[tuple[Path, int]] = []

    for ctx_name, ctx in contexts.items():
        names: dict[str, Source] = ctx["names"]
        if not names:
            continue
        groups: dict[tuple[str, str], Source] = {}
        targets_by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
        for target, src in names.items():
            key = (src.provider, src.stem)
            groups[key] = groups[key].merged_with(src) if key in groups else src
            targets_by_key[key].append(target)

        stems = Counter(src.stem for src in groups.values())
        canonical: dict[tuple[str, str], str] = {}
        for key, src in groups.items():
            suffix = f"-{src.provider}" if stems[src.stem] > 1 else ""
            if ctx_name in UI_CONTEXTS:
                name = src.stem + suffix
            else:
                own = src.stem in names and (names[src.stem].provider, names[src.stem].stem) == key
                name = (src.stem if own else sorted(targets_by_key[key])[0]) + suffix
            canonical[key] = sanitize(name)

        ctx_sizes = CTX_SIZES.get(ctx_name, sizes)
        jobs: list[tuple[Path, int]] = []
        for key, src in groups.items():
            for size in ctx_sizes:
                art = src.pick_art(size)
                if art is not None:
                    jobs.append((art, size))
        all_jobs.extend(jobs)
        plans.append((ctx_name, names, groups, targets_by_key, canonical, ctx_sizes, jobs))

        mix = Counter(src.provider for target, src in names.items())
        report.setdefault("sources", {})[ctx_name] = dict(sorted(mix.items()))

    files = rasterize_many(all_jobs)

    for ctx_name, names, groups, targets_by_key, canonical, ctx_sizes, jobs in plans:
        for size in ctx_sizes:
            ctx_dir = theme_dir / ctx_name / str(size)
            ctx_dir.mkdir(parents=True, exist_ok=True)
            for key, src in groups.items():
                art = src.pick_art(size)
                if art is None:
                    continue
                dest = ctx_dir / f"{canonical[key]}.png"
                if dest.exists() or dest.is_symlink():
                    continue
                cached = files[(art, size)]
                if args.copy_aliases:
                    shutil.copy2(cached, dest)
                else:
                    place_file(cached, dest)
                stats[f"{ctx_name}:files"] += 1
            for target, src in names.items():
                key = (src.provider, src.stem)
                if target == canonical[key] or not groups[key].has_fixed_art():
                    continue
                dest = ctx_dir / f"{target}.png"
                if dest.exists() or dest.is_symlink():
                    continue
                if link_alias(dest, canonical[key]):
                    stats[f"{ctx_name}:links"] += 1
                else:
                    report["conflicts"].append(f"{ctx_name}/{size}: alias {target} blocked")

        if ctx_name not in SYMBOLIC_CONTEXTS:
            continue
        symbolic = theme_dir / ctx_name / "symbolic"
        symbolic.mkdir(parents=True, exist_ok=True)
        written: set[tuple[str, str]] = set()
        for target, src in names.items():
            if not target.endswith("-symbolic"):
                continue
            key = (src.provider, src.stem)
            art = src.symbolic
            if art is None and src.path is not None and src.path.suffix.lower() == ".svg":
                art = src.path
            if art is None:
                report["warnings"].append(f"{ctx_name}/symbolic: {target} has no recolourable artwork")
                continue
            dest = symbolic / f"{canonical[key]}.svg"
            if dest.exists():
                continue
            text = art.read_text(encoding="utf-8")
            text = re.sub(r'fill="(?!none)[^"]*"', 'fill="currentColor"', text)
            dest.write_text(text, encoding="utf-8")
            if key not in written:
                stats[f"{ctx_name}:symbolic"] += 1
                written.add(key)
        for target, src in names.items():
            if not target.endswith("-symbolic"):
                continue
            key = (src.provider, src.stem)
            real = symbolic / f"{canonical[key]}.svg"
            dest = symbolic / f"{target}.svg"
            if dest.exists() or dest.is_symlink() or not real.exists() or dest == real:
                continue
            os.symlink(f"{canonical[key]}.svg", dest)
            stats[f"{ctx_name}:symbolic-links"] += 1

    return stats


INPUT_SOURCES: dict[str, Path] = {}


# --------------------------------------------------------------------------- #
# stage F — index.theme, cache, reports, archive
# --------------------------------------------------------------------------- #
def write_index_theme(theme_dir: Path, theme_name: str, inherit: str, sizes: list[int]) -> None:
    dirs: list[str] = []
    entries: list[tuple[str, str, int | None]] = []
    for ctx, context in CTX_SPEC.items():
        if not (theme_dir / ctx).is_dir():
            continue
        for size in CTX_SIZES.get(ctx, sizes):
            if (theme_dir / ctx / str(size)).is_dir():
                dirs.append(f"{ctx}/{size}")
                entries.append((f"{ctx}/{size}", context, size))
        if ctx in SYMBOLIC_CONTEXTS and (theme_dir / ctx / "symbolic").is_dir():
            dirs.append(f"{ctx}/symbolic")
            entries.append((f"{ctx}/symbolic", context, None))
    lines = [
        "[Icon Theme]",
        f"Name={theme_name}",
        "Comment=Material file icons + Colloid system UI for Cinnamon "
        f"(generated from vscode-material-icon-theme {VERSION})",
        f"Inherits={inherit}",
        "Example=folder",
        "Hidden=false",
        f"Directories={','.join(dirs)}",
    ]
    for name, context, size in entries:
        if size is None:
            lines += ["", f"[{name}]", "Size=16", "MinSize=1", "MaxSize=512", f"Context={context}", "Type=Scalable"]
        else:
            lines += ["", f"[{name}]", f"Size={size}", f"Context={context}", "Type=Fixed"]
    (theme_dir / "index.theme").write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_cache(theme_dir: Path, report: dict) -> None:
    tool = shutil.which("gtk-update-icon-cache")
    if not tool:
        report["notes"].append("gtk-update-icon-cache not found, cache not built")
        return
    proc = subprocess.run([tool, "-f", "-q", str(theme_dir)], capture_output=True, text=True)
    if proc.returncode != 0:
        report["warnings"].append(f"gtk-update-icon-cache failed: {proc.stderr.strip()[:200]}")
    else:
        report["notes"].append("icon-theme.cache built")


def theme_coverage(theme_dir: Path, reference: Path, context: str) -> dict:
    ref_dir = reference / context / "48"
    if not ref_dir.is_dir():
        for candidate in sorted(reference.glob(f"{context}/*")):
            if candidate.is_dir() and candidate.name.isdigit():
                ref_dir = candidate
                break
    if not ref_dir.is_dir():
        return {}
    names = {p.stem for p in ref_dir.iterdir() if p.suffix in (".png", ".svg")}
    if context == "places":
        names -= THIRD_PARTY_PLACES
    # GTK looks names up per size, not per context, so a name the theme ships in
    # any context answers a request made from any other one (this is how the
    # Colloid apps table answers `system-file-manager`, formerly a places name).
    ours = theme_names(theme_dir)
    hit = sorted(names & ours)
    return {"reference": str(reference.name), "context": context, "total": len(names), "covered": len(hit), "missing": sorted(names - ours)}


_LABELS: set[str] = set()


_GENERIC_LABELS = {
    "image-x-generic": "image",
    "video-x-generic": "video",
    "audio-x-generic": "audio",
    "font-x-generic": "font",
    "text-x-generic": "text",
    "application-x-executable": "exec",
    "inode-directory": "folder",
}


def short_label(name: str, index: int) -> str:
    """Compact, unique label for the preview contact sheet."""
    if name in _GENERIC_LABELS:
        return _GENERIC_LABELS[name]
    base = name
    for prefix in (
        "application-vnd.openxmlformats-officedocument.",
        "application-vnd.",
        "application-x-",
        "application-",
        "applications-",
        "preferences-",
        "text-x-",
        "text-",
        "image-x-",
        "video-x-",
        "audio-x-",
        "font-x-",
        "folder-",
        "user-",
    ):
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    base = base[:12]
    if base in _LABELS:
        base = f"{base[:9]}~{index}"
    _LABELS.add(base)
    return base


UI_PICKS: list[tuple[str, str]] = [
    ("apps", "accessories-text-editor"),
    ("apps", "preferences-desktop"),
    ("apps", "system-file-manager"),
    ("apps", "cs-notifications"),
    ("apps", "mintinstall"),
    ("apps", "gnome-terminal"),
    ("apps", "pix"),
    ("apps", "timeshift"),
    ("actions", "system-shutdown"),
    ("actions", "system-reboot"),
    ("actions", "system-log-out"),
    ("actions", "system-lock-screen"),
    ("actions", "window-close"),
    ("actions", "edit-copy"),
    ("actions", "document-open"),
    ("actions", "view-refresh"),
    ("status", "notifications"),
    ("status", "audio-volume-high"),
    ("status", "network-wireless-signal-good"),
    ("status", "battery-good"),
    ("status", "dialog-error"),
    ("status", "dialog-warning"),
    ("devices", "printer"),
    ("devices", "drive-harddisk"),
    ("devices", "media-cdrom"),
    ("devices", "input-mouse"),
    ("categories", "applications-games"),
    ("categories", "applications-graphics"),
    ("categories", "preferences-desktop-theme"),
    ("categories", "applications-system"),
]


def make_preview(
    theme_dir: Path,
    out_file: Path,
    picks: list[tuple[str, str]] | None = None,
    title: str | None = None,
) -> None:
    picks = picks or [
        ("places", "folder"),
        ("places", "folder-open"),
        ("places", "user-home"),
        ("places", "user-trash"),
        ("places", "folder-docs"),
        ("places", "folder-download"),
        ("places", "folder-images"),
        ("places", "folder-audio"),
        ("places", "folder-video"),
        ("places", "folder-template"),
        ("places", "folder-public"),
        ("places", "folder-app"),
        ("places", "folder-connection"),
        ("places", "folder-src"),
        ("places", "start-here"),
        ("mimetypes", "text-x-python"),
        ("mimetypes", "text-x-javascript"),
        ("mimetypes", "application-json"),
        ("mimetypes", "text-html"),
        ("mimetypes", "text-css"),
        ("mimetypes", "text-markdown"),
        ("mimetypes", "application-pdf"),
        ("mimetypes", "application-zip"),
        ("mimetypes", "application-msword"),
        ("mimetypes", "application-vnd.ms-excel"),
        ("mimetypes", "application-vnd.ms-powerpoint"),
        ("mimetypes", "image-x-generic"),
        ("mimetypes", "video-x-generic"),
        ("mimetypes", "audio-x-generic"),
        ("mimetypes", "font-x-generic"),
        ("mimetypes", "text-x-java"),
        ("mimetypes", "text-x-go"),
        ("mimetypes", "text-x-rust"),
        ("mimetypes", "text-x-csrc"),
        ("mimetypes", "text-x-c++"),
        ("mimetypes", "text-x-csharp"),
        ("mimetypes", "application-x-executable"),
        ("mimetypes", "text-x-generic"),
        ("mimetypes", "inode-directory"),
        ("categories", "applications-development"),
        ("categories", "applications-games"),
        ("categories", "applications-graphics"),
        ("categories", "applications-internet"),
        ("categories", "applications-office"),
        ("categories", "applications-system"),
        ("categories", "applications-multimedia"),
        ("categories", "preferences-desktop"),
    ]
    cell, icon_size, cols = 96, 64, 8
    rows = (len(picks) + cols - 1) // cols
    width, height = cols * cell, rows * (cell + 18) + 24
    canvas = Image.new("RGBA", (width, height), (24, 24, 34, 255))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 11)
    except OSError:
        font = ImageFont.load_default()
    draw.text((10, 6), title or f"{theme_dir.name} — icon preview", fill=(205, 214, 244, 255), font=font)
    for index, (ctx, name) in enumerate(picks):
        path = theme_dir / ctx / "64" / f"{name}.png"
        if not path.exists():
            path = theme_dir / ctx / "48" / f"{name}.png"
        if not path.exists():
            continue
        col, row = index % cols, index // cols
        x, y = col * cell + (cell - icon_size) // 2, 24 + row * (cell + 18)
        with Image.open(path) as icon:
            icon = icon.convert("RGBA")
            if icon.size != (icon_size, icon_size):
                icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
            canvas.alpha_composite(icon, (x, y))
        label = short_label(name, index)
        try:
            tw = draw.textlength(label, font=font)
        except Exception:
            tw = len(label) * 6
        draw.text((col * cell + (cell - tw) / 2, y + icon_size + 2), label, fill=(166, 173, 200, 255), font=font)
    canvas.convert("RGB").save(out_file, "PNG", optimize=True)


def theme_names(theme_dir: Path) -> set[str]:
    """Every icon name the theme ships, in any context and size directory."""
    names: set[str] = set()
    for context_dir in theme_dir.iterdir():
        if not context_dir.is_dir():
            continue
        for sub in context_dir.iterdir():
            if sub.is_dir():
                names |= {p.stem for p in sub.iterdir() if p.suffix in (".png", ".svg")}
    return names


def _stem_set(root: Path) -> set[str]:
    names: set[str] = set()
    if not root.is_dir():
        return names
    for path in root.rglob("*"):
        if not (path.is_file() or path.is_symlink()):
            continue
        stem = path.name
        for suffix in (".png", ".svg", ".xpm"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        names.add(re.sub(r"@2x$", "", stem))
    return names


def required_coverage(theme_dir: Path, required: Path, inherited: dict[str, Path] | None = None) -> dict:
    """Resolve every name the live desktop asks for to the theme that answers it.

    ``theme`` is what this build provides; anything else is answered further down
    the Inherits chain. Names only ``mint`` knows are the ones the theme still has
    to borrow from a restyled Mint icon — i.e. the real gaps.
    """
    inherited = inherited or {}
    rows: list[tuple[str, str, str]] = []
    for raw in required.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 2:
            continue
        rows.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))

    have_theme: dict[str, set[str]] = {}
    for context_dir in theme_dir.iterdir():
        if not context_dir.is_dir():
            continue
        names: set[str] = set()
        for sub in context_dir.iterdir():
            if sub.is_dir():
                names |= {p.stem for p in sub.iterdir() if p.suffix in (".png", ".svg")}
        have_theme[context_dir.name] = names
    have_all = theme_names(theme_dir)

    other = {name: _stem_set(path) for name, path in inherited.items()}
    per_context: dict[str, dict] = {}
    for context, name, origin in rows:
        bucket = per_context.setdefault(
            context, {"total": 0, "covered": 0, "sources": {}, "missing": [], "origins": {}}
        )
        bucket["total"] += 1
        bucket["origins"][origin] = bucket["origins"].get(origin, 0) + 1
        if name in have_all:
            source = "theme"
            bucket["covered"] += 1
        else:
            source = next((label for label, names in other.items() if name in names), "none")
            bucket["missing"].append(f"{name} ({source})")
        bucket["sources"][source] = bucket["sources"].get(source, 0) + 1
    return per_context


def make_report(report: dict, theme_dir: Path, coverage: list[dict], stats: Counter, out_file: Path) -> None:
    total = sum(p.stat().st_size for p in theme_dir.rglob("*") if p.is_file() and not p.is_symlink())
    links = sum(1 for p in theme_dir.rglob("*") if p.is_symlink())
    names = sum(1 for p in theme_dir.rglob("*.png"))
    lines = [
        f"# {theme_dir.name} build report",
        "",
        f"- source: `{report['source']}` v{VERSION}",
        f"- generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- theme dir: `{theme_dir}`",
        f"- sizes: {', '.join(str(s) for s in report['sizes'])}",
        f"- inherits: `{report['inherit']}`",
        "",
        "## counts",
        "",
        "| context | real png | symlinks |",
        "| --- | ---: | ---: |",
    ]
    for ctx in CTX_SPEC:
        lines.append(f"| {ctx} | {stats[f'{ctx}:files']} | {stats[f'{ctx}:links']} |")
    lines += [
        f"| **total** | **{names}** | **{links}** |",
        "",
        f"- PNG payload: {human(total)}",
        "",
        "## artwork sources",
        "",
        "| context | colloid | file icon |",
        "| --- | ---: | ---: |",
    ]
    for ctx in CTX_SPEC:
        mix = report.get("sources", {}).get(ctx)
        if not mix:
            continue
        lines.append("| {} | {} | {} |".format(ctx, mix.get("colloid", 0), mix.get("file", 0)))
    lines += [
        "",
        f"- Colloid snapshot: {report.get('colloid', {}).get('icons', 0)} names "
        f"({report.get('colloid', {}).get('variant', '?')} variant)",
        "",
    ]
    required = report.get("required")
    if required:
        lines += [
            "## required names (live desktop)",
            "",
            f"- source: `{report['required_path']}`",
            "- `theme` = answered by this theme, the rest falls through the Inherits chain;",
            "  only `mint`/`none` mean the name is still borrowed from a restyled Mint icon.",
            "",
            "| context | theme | adwaita | hicolor | mint | none | total |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for context, bucket in sorted(required.items()):
            src = bucket["sources"]
            lines.append(
                "| {} | {} | {} | {} | {} | {} | {} |".format(
                    context,
                    src.get("theme", 0),
                    src.get("adwaita", 0),
                    src.get("hicolor", 0),
                    src.get("mint", 0),
                    src.get("none", 0),
                    bucket["total"],
                )
            )
        for context, bucket in sorted(required.items()):
            left = [name for name in bucket["missing"] if "(mint)" in name or "(none)" in name]
            if not left:
                continue
            lines += ["", f"### still borrowed in `{context}` ({len(left)})", ""]
            lines += [f"- `{name}`" for name in left[:40]]
            if len(left) > 40:
                lines.append(f"- … (+{len(left) - 40} more)")
        lines.append("")
    lines += [
        "## mimetypes",
        "",
        f"- MIME types known to the system: {report['mime_stats']['system_mimes']}",
        f"- matched by class rules: {report['mime_stats']['from_rules']}",
        f"- explicit table entries: {report['mime_stats']['exact_entries']}",
        f"- emitted names: {report['mime_stats']['emitted']}",
        "",
        "## reference theme coverage",
        "",
        "| context | reference | covered | total |",
        "| --- | --- | ---: | ---: |",
    ]
    for row in coverage:
        if row:
            lines.append(f"| {row['context']} | {row['reference']} | {row['covered']} | {row['total']} |")
    for row in coverage:
        if not row or not row["missing"]:
            continue
        missing = row["missing"]
        head = missing[:12]
        more = "" if len(missing) <= 12 else f" … (+{len(missing) - 12} more)"
        lines += [
            "",
            f"### inherited `{row['context']}` names ({len(missing)}, provided by the parent theme)",
            "",
            ", ".join(f"`{n}`" for n in head) + more,
        ]
    lists = [
        ("generated icons", report["generated"]),
        ("clone fallbacks", [f"{k}: {v}" for k, v in report["clone_fallbacks"].items()]),
        ("missing sources (skipped)", report["missing_sources"]),
        ("name conflicts", report["conflicts"]),
        ("notes", report["notes"]),
        ("warnings", report["warnings"]),
    ]
    for title, items in lists:
        lines += ["", f"## {title}", ""]
        if items:
            lines += [f"- {i}" for i in items[:40]]
            if len(items) > 40:
                lines.append(f"- … and {len(items) - 40} more")
        else:
            lines.append("- none")
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_archive(theme_dir: Path, out_file: Path) -> None:
    with tarfile.open(out_file, "w:xz", preset=6) as tar:
        tar.add(theme_dir, arcname=theme_dir.name)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", default=",".join(str(s) for s in DEFAULT_SIZES), help="comma separated pixel sizes")
    parser.add_argument("--theme-name", default=DEFAULT_THEME)
    parser.add_argument(
        "--inherit",
        default=None,
        help=f"Inherits chain (default: {DEFAULT_INHERIT}; Mint-Y is last so uncovered apps keep their vendor icons)",
    )
    parser.add_argument("--out", default=str(OUT), help=f"output directory (default: {OUT})")
    parser.add_argument("--icons", default=None, help="icon source root containing file/ and folder/ (default: <repo>/icons)")
    parser.add_argument("--maps", default=None, help="mapping table directory (default: <repo>/mappings)")
    parser.add_argument("--upstream", default=None, help="vscode-material-icon-theme checkout, needed by --refresh-maps")
    parser.add_argument("--reference", default="/usr/share/icons/Mint-Y", help="reference theme for the coverage report")
    parser.add_argument(
        "--required",
        default=None,
        help="TSV of context/name/origin the desktop asks for (tools/collect-required.py); reports what is still missing",
    )
    parser.add_argument("--copy-aliases", action="store_true", help="copy instead of symlink aliases")
    parser.add_argument("--no-apps", action="store_true", help="skip the applications context")
    parser.add_argument("--colloid-assets", default=None, help="vendored Colloid artwork (default: assets/colloid)")
    parser.add_argument(
        "--renderer",
        default="auto",
        choices=("auto", "resvg", "inkscape"),
        help="SVG rasteriser: auto uses resvg-py when installed, else the Inkscape CLI",
    )
    parser.add_argument("--no-extra-folder-names", action="store_true", help="do not expose material folder names as place names")
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--refresh-maps", action="store_true", help="re-extract the mapping snapshot from --upstream")
    parser.add_argument("--dry-run", action="store_true", help="resolve mappings and print statistics only")
    args = parser.parse_args(argv)

    sizes = sorted({int(s) for s in args.sizes.split(",") if s.strip()})
    if not sizes:
        raise SystemExit("no sizes given")

    global INPUT_SOURCES, SRC_FILE, SRC_FOLDER, MAPS, COLLOID, COLLOID_ASSETS, RENDERER
    started = time.time()
    report: dict = {
        "source": "material-icon-theme",
        "generated": [],
        "clone_fallbacks": {},
        "missing_sources": [],
        "conflicts": [],
        "warnings": [],
        "notes": [],
        "sizes": sizes,
        "sources": {},
    }

    RENDERER = args.renderer
    log(f"svg renderer: {svg_renderer()}")
    if args.colloid_assets:
        COLLOID_ASSETS = Path(args.colloid_assets).expanduser().resolve()
    COLLOID = load_colloid(MAPS / "colloid-index.json", report)
    log(f"colloid: {len(COLLOID)} mapped names from {COLLOID_ASSETS.relative_to(REPO)}")

    if args.icons:
        icon_root = Path(args.icons).expanduser().resolve()
        SRC_FILE, SRC_FOLDER = icon_root / "file", icon_root / "folder"
    if args.maps:
        MAPS = Path(args.maps).expanduser().resolve()
    upstream = Path(args.upstream).expanduser().resolve() if args.upstream else None

    maps = load_maps(args.refresh_maps, upstream)
    global VERSION, PROJECT_VERSION
    VERSION = maps.get("version") or lock_version()
    PROJECT_VERSION = project_version()

    inherits = args.inherit or detect_inherit(args.theme_name)
    report["inherit"] = inherits

    generated = generate_folder_icons(report) if not args.dry_run else {}
    sources = discover_sources(generated)
    INPUT_SOURCES = sources
    clones = {ic["name"]: ic["clone"] for ic in maps["fileIcons"] if ic.get("clone")}
    log(f"{len(sources)} source icons, {len(maps['fileIcons'])} file mappings")

    contexts = build_tables(maps, sources, clones, args, report)
    for ctx, data in contexts.items():
        log(f"{ctx}: {len(data['names'])} names")
    if args.dry_run:
        log("dry run, nothing written")
        return 0

    out_dir = Path(args.out).expanduser().resolve()
    theme_dir = out_dir / args.theme_name
    if theme_dir.exists():
        shutil.rmtree(theme_dir)
    theme_dir.mkdir(parents=True)

    stats = materialize(contexts, sizes, theme_dir, args, report)
    write_index_theme(theme_dir, args.theme_name, inherits, sizes)
    for notice in NOTICE_FILES:
        notice_file = REPO / notice
        if notice_file.exists():
            shutil.copy2(notice_file, theme_dir / notice)
    # The Colloid artwork is GPL-3.0; the built theme must carry that licence too.
    colloid_license = COLLOID_ASSETS / "LICENSE"
    if colloid_license.exists():
        shutil.copy2(colloid_license, theme_dir / "LICENSE-Colloid")
    update_cache(theme_dir, report)

    reference = Path(args.reference).expanduser()
    coverage = [theme_coverage(theme_dir, reference, ctx) for ctx in ("places", "mimetypes", "apps", "categories", "devices")]
    if args.required:
        required_path = Path(args.required).expanduser()
        if required_path.exists():
            required = required_coverage(
                theme_dir,
                required_path,
                inherited={
                    "adwaita": Path("/usr/share/icons/Adwaita"),
                    "hicolor": Path("/usr/share/icons/hicolor"),
                    "mint": reference,
                },
            )
            report["required"] = required
            report["required_path"] = str(required_path)
            for context, bucket in sorted(required.items()):
                log(f"required {context}: {bucket['covered']}/{bucket['total']} covered")
        else:
            report["warnings"].append(f"--required file not found: {required_path}")
    make_report(report, theme_dir, coverage, stats, out_dir / "report.md")
    make_preview(theme_dir, out_dir / "preview.png")
    make_preview(
        theme_dir,
        out_dir / "ui-preview.png",
        picks=UI_PICKS,
        title=f"{args.theme_name} — system UI (Colloid artwork)",
    )
    (out_dir / "build.json").write_text(
        json.dumps(
            {
                "theme": args.theme_name,
                "source": report["source"],
                "version": PROJECT_VERSION,
                "upstream_version": VERSION,
                "sizes": sizes,
                "inherit": inherits,
                "counts": {ctx: len(contexts[ctx]["names"]) for ctx in contexts},
                "sources": report.get("sources", {}),
                "colloid": report.get("colloid", {}),
                "files": {k: v for k, v in stats.items()},
                "coverage": [
                    {k: v for k, v in row.items() if k != "missing"} for row in coverage if row
                ],
                "required": {
                    context: {k: v for k, v in bucket.items() if k != "missing"}
                    for context, bucket in (report.get("required") or {}).items()
                },
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    if not args.no_archive:
        archive = out_dir / f"{args.theme_name}-{PROJECT_VERSION}.tar.xz"
        if archive.exists():
            archive.unlink()
        make_archive(theme_dir, archive)
        log(f"archive: {archive.relative_to(REPO)} ({human(archive.stat().st_size)})")

    log(f"done in {time.time() - started:.1f}s -> {theme_dir}")
    return 0


def project_version() -> str:
    """This project's own version (the VERSION file), not the upstream pin."""
    try:
        return (REPO / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def lock_version() -> str:
    """Read the pinned upstream version from upstream.lock.json."""
    lock = REPO / "upstream.lock.json"
    try:
        return str(json.loads(lock.read_text(encoding="utf-8")).get("version") or "unknown")
    except (OSError, ValueError):
        return "unknown"


def detect_inherit(theme_name: str) -> str:
    """Inherits chain used when --inherit is not given.

    Fixed rather than derived from the active Cinnamon theme. Deriving it meant a
    machine that was running `Mint-Y-Sand` baked `Mint-Y-Sand,Mint-Y` in front of
    `hicolor`, so names this theme does not ship (Firefox, Thunderbird, most
    third-party apps) came from Mint's restyled app icons instead of the vendor
    artwork in `hicolor`. `Mint-Y` now sits last, so it only answers names that
    neither Adwaita nor hicolor know — the shell's own action/status icons.
    """
    del theme_name  # kept for signature compatibility with older call sites
    return DEFAULT_INHERIT


NOTICE_FILES = (
    "LICENSE",
    "LICENSE-MIT",
    "LICENSE-Material",
    "LICENSE-Apache-2.0",
    "ATTRIBUTION.md",
)

VERSION = "unknown"  # pinned vscode-material-icon-theme release (upstream)
PROJECT_VERSION = "0.0.0"  # this project's own VERSION file

if __name__ == "__main__":
    sys.exit(main())
