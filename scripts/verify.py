#!/usr/bin/env python3
"""Validate the generated Cinnamon-Mosaic icon theme.

Checks
------
1. ``index.theme`` is parseable and every listed directory exists, is non-empty
   and carries Size/Context/Type keys.
2. Every directory on disk is declared in ``index.theme``.
3. Every symlink resolves; no broken links, no cycles.
4. A sample of PNGs decodes and matches the directory pixel size (plus a full
   header check of every real file is done for all sizes on request).
5. Coverage against the reference theme (Mint-Y) and the expected minimums.
6. ``gtk-update-icon-cache`` builds and validates the cache.
7. Optional: a real GTK icon lookup through the system PyGObject, when present.

Exit code 0 means the theme is installable.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MIN_NAMES = {"places": 200, "mimetypes": 500}

# Third-party applications are resolved through hicolor on purpose (no artwork
# in this theme), so Mint-Y's restyled copies are not a coverage reference.
THIRD_PARTY_PLACES = {
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
EXPECTED_COVERAGE = {"places": 0.95, "mimetypes": 0.90}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the generated Cinnamon-Mosaic icon theme.")
    parser.add_argument("theme", nargs="?", default=str(REPO / "dist" / "Cinnamon-Mosaic"))
    parser.add_argument("--reference", default="/usr/share/icons/Mint-Y", help="reference theme for the coverage check")
    parser.add_argument(
        "--require-coverage",
        action="store_true",
        help="fail when the reference theme is missing or coverage is below the threshold",
    )
    args = parser.parse_args(argv)
    theme = Path(args.theme).expanduser().resolve()
    reference_dir = Path(args.reference).expanduser()
    errors: list[str] = []
    warnings: list[str] = []
    checked = {"dirs": 0, "files": 0, "links": 0, "png": 0}

    if not theme.is_dir():
        print(f"FAIL theme directory not found: {theme}")
        return 1

    index = theme / "index.theme"
    if not index.exists():
        print(f"FAIL missing index.theme in {theme}")
        return 1

    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # keep case, Size/Directories matter
    parser.read(index, encoding="utf-8")
    if "Icon Theme" not in parser:
        errors.append("index.theme has no [Icon Theme] section")
        print("\n".join(errors))
        return 1

    meta = parser["Icon Theme"]
    for key in ("Name", "Inherits", "Directories"):
        if not meta.get(key):
            errors.append(f"[Icon Theme] missing required key {key}")

    declared = [d.strip() for d in meta.get("Directories", "").split(",") if d.strip()]
    if not declared:
        errors.append("Directories is empty")

    # 1/2 — declared <-> on disk
    on_disk = set()
    for context_dir in theme.iterdir():
        if not context_dir.is_dir() or context_dir.name.startswith("."):
            continue
        for size_dir in context_dir.iterdir():
            if size_dir.is_dir():
                on_disk.add(f"{context_dir.name}/{size_dir.name}")
    for rel in declared:
        target = theme / rel
        checked["dirs"] += 1
        if not target.is_dir():
            errors.append(f"declared directory missing: {rel}")
            continue
        entries = list(target.iterdir())
        if not entries:
            errors.append(f"declared directory empty: {rel}")
        section = parser[rel] if parser.has_section(rel) else None
        if section is None:
            errors.append(f"missing section for directory: {rel}")
            continue
        for key in ("Size", "Context", "Type"):
            if not section.get(key):
                errors.append(f"[{rel}] missing {key}")
        # GTK uses these as the colourise source for "*-symbolic" names, so they
        # carry no pixel size of their own — they must be scalable instead.
        scalable = rel.split("/")[-1] == "symbolic"
        try:
            size = int(section.get("Size", "0"))
        except ValueError:
            errors.append(f"[{rel}] Size is not an integer")
            continue
        if section.get("Type", "").lower() not in ("fixed", "scalable", "threshold"):
            errors.append(f"[{rel}] unexpected Type")
        if scalable:
            if section.get("Type", "").lower() != "scalable":
                errors.append(f"[{rel}] symbolic directory must be Type=Scalable")
            for key in ("MinSize", "MaxSize"):
                if not section.get(key):
                    errors.append(f"[{rel}] symbolic directory missing {key}")
            if not any(p.suffix == ".svg" for p in target.rglob("*")):
                errors.append(f"[{rel}] symbolic directory holds no SVG")
        elif rel.split("/")[-1] != str(size):
            errors.append(f"[{rel}] directory name and Size disagree")
    for rel in sorted(on_disk - set(declared)):
        warnings.append(f"directory not declared in index.theme: {rel}")

    # 3 — symlinks
    for path in theme.rglob("*"):
        if not path.is_symlink():
            continue
        checked["links"] += 1
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            errors.append(f"broken symlink: {path.relative_to(theme)} ({exc})")
            continue
        if not resolved.is_file():
            errors.append(f"symlink does not point to a file: {path.relative_to(theme)}")
        if os.path.realpath(path) == os.path.realpath(path.parent):
            errors.append(f"symlink cycle: {path.relative_to(theme)}")

    # 4 — PNG headers
    for context_dir in theme.iterdir():
        if not context_dir.is_dir():
            continue
        for size_dir in context_dir.iterdir():
            if not size_dir.is_dir() or not size_dir.name.isdigit():
                continue
            expected = int(size_dir.name)
            for png in size_dir.iterdir():
                checked["files"] += 1
                if png.is_symlink():
                    continue
                if png.suffix != ".png":
                    warnings.append(f"unexpected file type: {png.relative_to(theme)}")
                    continue
                with png.open("rb") as handle:
                    head = handle.read(33)
                if head[:8] != b"\x89PNG\r\n\x1a\n":
                    errors.append(f"not a PNG: {png.relative_to(theme)}")
                    continue
                width, height = struct.unpack(">II", head[16:24])
                if (width, height) != (expected, expected):
                    errors.append(f"{png.relative_to(theme)} is {width}x{height}, expected {expected}")
                checked["png"] += 1

    # 5 — coverage of the reference theme
    reference = reference_dir
    coverage: list[tuple[str, int, int]] = []
    if reference.is_dir():
        for context, minimum in MIN_NAMES.items():
            ref = reference / context / "48"
            if not ref.is_dir():
                continue
            ref_names = {p.stem for p in ref.iterdir() if p.suffix in (".png", ".svg")}
            if context == "places":
                ref_names -= THIRD_PARTY_PLACES
            ours: set[str] = set()
            for size_dir in (theme / context).glob("*"):
                if size_dir.is_dir():
                    ours |= {p.stem for p in size_dir.iterdir()}
            # GTK resolves names per size, not per context, so coverage is
            # measured against every name the theme ships.
            covered = len(ref_names & theme_names(theme))
            coverage.append((context, covered, len(ref_names)))
            ratio = covered / max(len(ref_names), 1)
            if ratio < EXPECTED_COVERAGE[context]:
                errors.append(f"{context} coverage {covered}/{len(ref_names)} below {EXPECTED_COVERAGE[context]:.0%}")
            if len(ours) < minimum:
                errors.append(f"{context} exposes only {len(ours)} names, expected >= {minimum}")
    else:
        message = f"reference theme {reference} not installed, coverage skipped"
        (errors if args.require_coverage else warnings).append(message)

    # 5b — the vendored Colloid snapshot is fully represented
    errors.extend(check_colloid(theme))

    # 5c — no third-party application artwork
    errors.extend(check_third_party(theme))

    # 6 — icon cache
    tool = "gtk-update-icon-cache"
    if shutil_which(tool):
        build = subprocess.run([tool, "-f", "-q", str(theme)], capture_output=True, text=True)
        if build.returncode != 0:
            errors.append(f"gtk-update-icon-cache failed: {build.stderr.strip()[:200]}")
        validate = subprocess.run([tool, "-v", str(theme)], capture_output=True, text=True)
        if validate.returncode != 0:
            errors.append(f"gtk-update-icon-cache --validate failed: {validate.stderr.strip()[:200]}")
        if not (theme / "icon-theme.cache").exists():
            errors.append("icon-theme.cache was not created")
    else:
        warnings.append("gtk-update-icon-cache not installed, cache check skipped")

    # 7 — optional real GTK lookup through the system interpreter
    lookup = gtk_lookup(
        theme,
        [
            "folder",
            "folder-open",
            "user-home",
            "start-here",
            "text-x-python",
            "application-pdf",
            "accessories-text-editor",
            "preferences-desktop",
            "system-file-manager",
            "system-shutdown",
            "notifications",
            "notification-active",
            "notification-inactive",
            "user-trash",
            "user-trash-full",
            "vscode",
            "window-close",
        ],
    )
    if lookup is None:
        warnings.append("PyGObject/GTK not available for a runtime lookup test")
    else:
        for name, filename in lookup.items():
            if filename is None:
                errors.append(f"GTK cannot resolve icon `{name}` in the theme")
            elif name in MUST_OWN and not filename.startswith(f"{theme}{os.sep}"):
                errors.append(f"GTK resolves `{name}` outside the theme: {filename}")

    # summary
    print(f"theme: {theme}")
    print(f"directories: {checked['dirs']}  entries: {checked['files']}  symlinks: {checked['links']}  png verified: {checked['png']}")
    for context, covered, total in coverage:
        print(f"coverage {context}: {covered}/{total} ({covered / max(total, 1):.1%})")
    if lookup is not None:
        print(
            "gtk lookup: "
            + ", ".join(f"{k}={Path(v).name if v else 'MISSING'}" for k, v in lookup.items())
        )
    for warning in warnings:
        print(f"WARN {warning}")
    if errors:
        print()
        for error in errors[:40]:
            print(f"FAIL {error}")
        if len(errors) > 40:
            print(f"FAIL … and {len(errors) - 40} more")
        return 1
    print("OK theme validated")
    return 0


def theme_names(theme: Path) -> set[str]:
    names: set[str] = set()
    for context_dir in theme.iterdir():
        if not context_dir.is_dir():
            continue
        for sub in context_dir.iterdir():
            if sub.is_dir():
                names |= {p.stem for p in sub.iterdir() if p.suffix in (".png", ".svg")}
    return names


def check_colloid(theme: Path) -> list[str]:
    """Every name in mappings/colloid-index.json must reach the built theme.

    The index records the Colloid source name; a desktop name normally becomes
    an alias of the PNG/SVG named after it, so the target name is what has to
    exist in every size directory (an override in mappings/extra.tsv can rename
    the Colloid artwork with a ``-colloid`` suffix, which is why the target, not
    the stem, is asserted).
    """
    index_path = REPO / "mappings" / "colloid-index.json"
    if not index_path.exists():
        return [f"missing {index_path.relative_to(REPO)} (run make vendor-colloid)"]
    icons = json.loads(index_path.read_text(encoding="utf-8")).get("icons", {})
    errors: list[str] = []
    for key, meta in sorted(icons.items()):
        context, _, target = key.partition("/")
        ctx_dir = theme / context
        if not ctx_dir.is_dir():
            errors.append(f"colloid: missing context directory {context}")
            continue
        stem = meta["source"]
        art_sizes = {d for d in meta.get("art", {})}
        for size_dir in sorted(ctx_dir.iterdir()):
            if not size_dir.is_dir() or not size_dir.name.isdigit():
                continue
            if art_sizes and not (size_dir / f"{target}.png").exists():
                errors.append(f"colloid: {context}/{size_dir.name}/{target}.png missing")
        if meta.get("symbolic") and not any(
            (ctx_dir / "symbolic" / f"{name}.svg").exists()
            for name in (target, stem, f"{stem}-colloid")
        ):
            errors.append(f"colloid: {context}/symbolic/{target}.svg missing")
        if target not in theme_names(theme):
            errors.append(f"colloid: {context}/{target} not emitted")
    return errors


# Names the theme must serve itself; resolving them through Inherits means a
# mapping went missing (this is how VS Code silently fell back to Mint-Y's
# restyled square).
MUST_OWN = (
    "notifications",
    "notification-active",
    "notification-inactive",
    "user-trash",
    "user-trash-full",
    "vscode",
)

THIRD_PARTY = (
    "vscode", "code", "codium", "chrome", "chromium", "blender", "figma", "sketch",
    "godot", "unity", "docker", "gitkraken", "sublime", "jupyter", "dbeaver",
    "mysql-workbench", "sqlitebrowser", "insomnia", "gitlab", "github", "steam",
    "spotify", "firefox", "thunderbird", "libreoffice",
)


def curated_apps() -> set[str]:
    """Application names published from mappings/apps.tsv."""
    path = REPO / "mappings" / "apps.tsv"
    names: set[str] = set()
    if not path.exists():
        return names
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line.split("\t")[0].strip().lower())
    return names


def check_third_party(theme: Path) -> list[str]:
    """Third-party applications resolve through hicolor; the theme must not
    ship artwork for them.

    The only exception is a curated row in mappings/apps.tsv -- a name whose
    logo already exists in the vendored Material set (VS Code). Those are
    checked the other way around: the artwork has to be there.
    """
    errors: list[str] = []
    allowed = curated_apps()
    apps_dir = theme / "apps"
    if not apps_dir.is_dir():
        return errors
    for path in apps_dir.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        stem = path.stem.lower()
        if stem in THIRD_PARTY and stem not in allowed:
            errors.append(f"third-party icon shipped: {path.relative_to(theme)}")
    for name in sorted(allowed & set(THIRD_PARTY)):
        if not (apps_dir / "48" / f"{name}.png").exists():
            errors.append(f"curated application icon missing: apps/48/{name}.png")
    return errors


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def gtk_lookup(theme: Path, names: list[str]) -> dict[str, str | None] | None:
    """Ask the system GTK3 (via PyGObject) which file it resolves a name to.

    The resolved path is what tells "shipped by this theme" apart from
    "inherited from Mint-Y" -- a name can resolve and still come from the
    parent theme, which is exactly how a lost icon goes unnoticed.
    """
    script = f"""
import sys
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
theme = Gtk.IconTheme.new()
theme.set_search_path([r'{theme.parent}'])
theme.set_custom_theme(r'{theme.name}')
for name in {names!r}:
    info = theme.lookup_icon(name, 48, 0)
    print(f"{{name}}={{info.get_filename() if info else ''}}")
"""
    try:
        proc = subprocess.run(["/usr/bin/python3", "-c", script], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    result: dict[str, str | None] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            name, path = line.rsplit("=", 1)
            result[name] = path.strip() or None
    return result or None


if __name__ == "__main__":
    sys.exit(main())
