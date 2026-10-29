#!/usr/bin/env python3
"""Vendor the Colloid artwork referenced by the Colloid mapping tables.

Colloid ships its artwork in ``src/`` (real SVGs, hand drawn per size) plus a
``links/`` overlay of freedesktop aliases (directory symlinks).  Both trees are
flattened into the installed theme, so a link is resolved *logically*: an
absolute target is trimmed back to the ``links/`` root, a relative target is
joined with the link's own directory, and the result is looked up in the link
index first and the source index second.  That makes the result independent of
where the checkout lives -- a tree whose links were rewritten to absolute paths
resolves to exactly the same artwork as a pristine clone.

    python3 tools/vendor-colloid-icons.py --colloid-dir ../Colloid-icon-theme
    python3 tools/vendor-colloid-icons.py --from-required      # refresh colloid-auto.tsv

Tables (all ``<context>\\t<desktop icon name>\\t<colloid icon name>``):

  mappings/colloid.tsv        curated, wins over everything else; ``-`` in the
                              third column means "leave this name to the
                              Material/file-icon fallback or the parent theme".
  mappings/colloid-auto.tsv   generated from mappings/required.tsv for the
                              actions/status/devices contexts only.

Output:

  assets/colloid/<ctx>/<size>/<icon>.svg   vendored artwork, source layout kept
  assets/colloid/LICENSE                   Colloid's GPL-3.0 text
  mappings/colloid-index.json              resolved per-target artwork + hashes
  upstream-colloid.lock.json               provenance (index.theme hash, counts)

``--check`` recomputes the index in memory and compares it with the committed
copy (including the artwork hashes) without writing anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAPS = REPO / "mappings"
ASSETS = REPO / "assets" / "colloid"
INDEX = MAPS / "colloid-index.json"
LOCK = REPO / "upstream-colloid.lock.json"
DEFAULT_COLLOID = REPO.parent / "Colloid-icon-theme"

# Fetch order when a name exists in several Colloid contexts.  The context the
# desktop asked for always comes first (see ``ColloidTree.art``).
CONTEXTS = ("actions", "apps", "categories", "devices", "places", "status", "emblems", "mimetypes")
FIXED = ("22", "24", "16", "32")
SIZES = FIXED + ("scalable",)
SYMBOLIC_SUFFIX = "-symbolic"
# Namespaces whose ``links/apps/scalable`` aliases may rename the artwork when a
# name is resolved from another context (``applications-python -> python``).
APP_NAMESPACES = ("applications-", "preferences-", "cs-", "org.")

# Only these contexts accept names harvested from mappings/required.tsv; apps
# stay curated so third-party desktop entries never leak into the theme.
AUTO_CONTEXTS = ("actions", "status", "devices")

# Same rule as scripts/build.py:sanitize() -- kept in sync by hand because
# build.py imports Pillow at module level and cannot be imported here.
def sanitize(name: str) -> str:
    n = str(name).strip().replace("/", "-")
    n = "".join(ch for ch in n if ch.isalnum() or ch in "._+-")
    return n.strip(".-")


# --------------------------------------------------------------------------- #
# logical resolution of the src/ + links/ overlay
# --------------------------------------------------------------------------- #
def _rel_parts(rel: str) -> tuple[str, str, str] | None:
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if len(parts) >= 3:
        return parts[0], parts[1], "/".join(parts[2:])
    if len(parts) == 2:
        # ``links/status/xsi-*.svg``: a flat directory is the symbolic layer
        return parts[0], "symbolic", parts[1]
    return None


class ColloidTree:
    """Name index over a Colloid checkout with path independent link resolution."""

    def __init__(self, root: Path):
        self.root = root
        self.src: dict[tuple[str, str, str], Path] = {}
        self.links: dict[tuple[str, str, str], Path] = {}
        self._memo: dict[tuple[str, str, str], Path | None] = {}
        self.assets: dict[str, Path] = {}  # asset-relative path -> source file
        self._scan()

    def _scan(self) -> None:
        src = self.root / "src"
        links = self.root / "links"
        if not src.is_dir():
            raise SystemExit(f"{self.root}: not a Colloid checkout (src/ missing)")
        for path in src.rglob("*.svg"):
            key = _rel_parts(path.relative_to(src).as_posix())
            if key:
                self.src[key] = path
        if links.is_dir():
            for path in links.rglob("*"):
                if not (path.is_file() or path.is_symlink()):
                    continue
                key = _rel_parts(path.relative_to(links).as_posix())
                if key:
                    self.links[key] = path

    def _target(self, link: Path) -> tuple[str, str, str] | None:
        raw = os.readlink(link)
        if not raw:
            return None
        if raw.startswith("/") or raw.startswith("\\"):
            marker = "/links/"
            cut = raw.find(marker)
            if cut < 0:
                return None
            rel = raw[cut + len(marker):]
        else:
            base = link.parent.relative_to(self.root / "links").as_posix()
            rel = posixpath.join(base, raw.replace("\\", "/"))
        rel = posixpath.normpath(rel)
        if rel.startswith(".."):
            return None
        return _rel_parts(rel)

    def resolve(self, key: tuple[str, str, str], depth: int = 0, seen: frozenset = frozenset()) -> Path | None:
        if key in self._memo:
            return self._memo[key]
        if depth > 12 or key in seen:
            self._memo[key] = None
            return None
        link = self.links.get(key)
        result: Path | None = None
        if link is not None:
            if link.is_symlink():
                target = self._target(link)
                if target:
                    result = self.resolve(target, depth + 1, seen | {key})
            else:
                result = link
        if result is None:
            result = self.src.get(key)
        self._memo[key] = result
        return result

    def asset(self, path: Path) -> str:
        """Register ``path`` and return its location inside assets/colloid.

        The installed theme flattens ``src/`` and ``links/`` into one tree, so
        the vendored copy drops that first component (``src/actions/22/x.svg``
        and ``links/actions/22/x.svg`` both become ``actions/22/x.svg``).
        """
        parts = path.relative_to(self.root).parts
        rel = "/".join(parts[1:]) if parts and parts[0] in ("src", "links") else "/".join(parts)
        previous = self.assets.get(rel)
        if previous is not None and previous.resolve() != path.resolve():
            raise SystemExit(f"asset name collision: {rel} ({previous} vs {path})")
        self.assets[rel] = path
        return rel

    def _contexts(self, ctx: str) -> tuple[str, ...]:
        return (ctx,) + tuple(c for c in CONTEXTS if c != ctx)

    def art(self, ctx: str, name: str) -> tuple[str, dict[str, str]] | None:
        """Size-directory artwork for ``name``; first context that has any wins.

        Cross-context hits are only trusted when the resolved file is still
        called ``<name>.svg``.  ``links/apps/scalable`` carries historical brand
        aliases (``nm-device-wireless.svg -> wicd.svg``), and following those
        would put a random application logo where a network indicator belongs.
        Inside the requested context every alias is honoured, because that is
        what the overlay is for (``gtk-cancel -> dialog-cancel``).
        """
        wanted = f"{name}.svg"
        for context in self._contexts(ctx):
            found: dict[str, str] = {}
            for size in SIZES:
                path = self.resolve((context, size, wanted))
                if path is None:
                    continue
                if context != ctx and path.name != wanted:
                    # ``links/apps/scalable`` mixes real freedesktop names with
                    # historical brand aliases; only the app/preferences
                    # namespaces are trusted to rename there.
                    if context != "apps" or not name.startswith(APP_NAMESPACES):
                        continue
                found[size] = self.asset(path)
            if found:
                return context, found
        return None

    def symbolic(self, ctx: str, stem: str) -> tuple[str, str] | None:
        for context in self._contexts(ctx):
            for candidate in (f"{stem}{SYMBOLIC_SUFFIX}.svg", f"{stem}.svg"):
                path = self.resolve((context, "symbolic", candidate))
                if path is not None:
                    return context, self.asset(path)
        return None


# --------------------------------------------------------------------------- #
# tables
# --------------------------------------------------------------------------- #
@dataclass
class Row:
    context: str
    target: str
    icon: str
    origin: str  # "curated" | "auto"
    lineno: int = 0


def read_table(path: Path, origin: str) -> list[Row]:
    rows: list[Row] = []
    if not path.exists():
        return rows
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        parts = [p for p in parts if p and not p.startswith("#")]
        if len(parts) < 3:
            raise SystemExit(f"{path}:{lineno}: expected <context>\\t<target>\\t<colloid icon>")
        rows.append(Row(parts[0], sanitize(parts[1]), parts[2], origin, lineno))
    return rows


def read_names(path: Path) -> set[str]:
    """Target names of a two-column table (``<name>\\t<icon>``)."""
    names: set[str] = set()
    if not path.exists():
        return names
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p for p in line.split("\t") if p.strip() and not p.strip().startswith("#")]
        if parts:
            names.add(sanitize(parts[0]))
    return names


def read_required(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        out.append((parts[0].strip(), sanitize(parts[1].strip())))
    return out


def merge_rows(curated: list[Row], auto: list[Row]) -> list[Row]:
    """Curated rows win; a curated ``-`` also suppresses the auto row.

    A target may only live in one context -- GTK looks names up per size, not per
    context, so a duplicate would make the winner depend on directory order.
    The first row (curated before auto, then context order) keeps the name.
    """
    seen: dict[tuple[str, str], Row] = {}
    owner: dict[str, str] = {}
    for row in curated + auto:
        key = (row.context, row.target)
        if key in seen:
            continue
        other = owner.get(row.target)
        if other is not None and other != row.context:
            continue
        seen[key] = row
        owner[row.target] = row.context
    return [seen[k] for k in sorted(seen)]


# --------------------------------------------------------------------------- #
# resolution of one target
# --------------------------------------------------------------------------- #
@dataclass
class Entry:
    target: str
    context: str
    icon: str
    art: dict[str, str] = field(default_factory=dict)
    symbolic: str | None = None
    origin: str = "curated"

    @property
    def files(self) -> list[str]:
        return sorted(set(self.art.values()) | ({self.symbolic} if self.symbolic else set()))


def resolve_row(tree: ColloidTree, row: Row) -> Entry | None:
    """Resolve one table row to vendored files, or None when Colloid has nothing."""
    if row.icon == "-":
        return None
    icon = row.icon
    base = icon[: -len(SYMBOLIC_SUFFIX)] if icon.endswith(SYMBOLIC_SUFFIX) else icon
    entry = Entry(target=row.target, context=row.context, icon=icon, origin=row.origin)

    hit = tree.art(row.context, base)
    if hit:
        _context, entry.art = hit
    if row.target.endswith(SYMBOLIC_SUFFIX):
        sym = tree.symbolic(row.context, base)
        if sym:
            _context, entry.symbolic = sym
    if not entry.art and not entry.symbolic:
        return None
    return entry


# --------------------------------------------------------------------------- #
# build the plan (index + files) without touching the tree
# --------------------------------------------------------------------------- #
def variant_bytes(data: bytes, variant: str) -> bytes:
    if variant == "dark":
        return data.decode("utf-8").replace("#363636", "#dedede").encode("utf-8")
    return data


def build_plan(
    tree: ColloidTree,
    rows: list[Row],
    variant: str,
    dry_run: bool = False,
) -> tuple[dict, dict[str, bytes], list[str]]:
    entries: dict[str, dict] = {}
    files: dict[str, bytes] = {}
    missing: list[str] = []

    for row in rows:
        entry = resolve_row(tree, row)
        key = f"{row.context}/{row.target}"
        if entry is None:
            if row.icon != "-":
                missing.append(f"{row.context}/{row.target} -> {row.icon}")
            continue
        if key in entries:
            previous = entries[key]
            if previous["source"] != entry.icon:
                raise SystemExit(f"conflicting rows for {key}: {previous['source']} vs {entry.icon}")
            continue
        digest = hashlib.sha256()
        for rel in entry.files:
            data = variant_bytes(tree.assets[rel].read_bytes(), variant)
            files[rel] = data
            digest.update(rel.encode("utf-8") + b"\0" + data)
        entries[key] = {
            "source": entry.icon,
            "origin": entry.origin,
            "art": dict(sorted(entry.art.items())),
            "symbolic": entry.symbolic,
            "from": entry.art.get("22") or entry.art.get("scalable") or entry.files[0],
            "sha256": digest.hexdigest(),
        }

    index = {
        "generated_by": "tools/vendor-colloid-icons.py",
        "source": "Colloid-icon-theme",
        "variant": variant,
        "index_theme_sha256": sha256_file(tree.root / "src" / "index.theme"),
        "src_svg": len(tree.src),
        "icons": dict(sorted(entries.items())),
    }
    return index, files, missing


def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #
def write_assets(root: Path, files: dict[str, bytes], source_root: Path) -> None:
    staging = root.with_name(root.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for rel, data in sorted(files.items()):
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    license_src = source_root / "LICENSE"
    if license_src.exists():
        shutil.copy2(license_src, staging / "LICENSE")
    if root.exists():
        shutil.rmtree(root)
    staging.rename(root)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def dump_index(index: dict) -> str:
    return json.dumps(index, indent=1, sort_keys=True) + "\n"


def check(root: Path, index: dict, files: dict[str, bytes]) -> int:
    problems: list[str] = []
    if not INDEX.exists():
        problems.append(f"missing {INDEX.relative_to(REPO)} (run make vendor-colloid)")
    else:
        committed = json.loads(INDEX.read_text(encoding="utf-8"))
        if committed != index:
            problems.append(f"{INDEX.relative_to(REPO)} is stale (run make vendor-colloid)")
    for rel, data in sorted(files.items()):
        path = root / rel
        if not path.exists():
            problems.append(f"missing artwork: {path.relative_to(REPO)}")
        elif path.read_bytes() != data:
            problems.append(f"artwork differs: {path.relative_to(REPO)}")
    if not problems:
        print(f"ok: {len(index['icons'])} icons, {len(files)} artwork files, index up to date")
        return 0
    for problem in problems[:40]:
        print(f"MISMATCH {problem}")
    if len(problems) > 40:
        print(f"MISMATCH … and {len(problems) - 40} more")
    return 1


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--colloid-dir", default=str(DEFAULT_COLLOID))
    parser.add_argument("--variant", default="light", choices=("light", "dark"),
                        help="light keeps Colloid's #363636 artwork, dark recolours it to #dedede")
    parser.add_argument("--from-required", action="store_true",
                        help="regenerate mappings/colloid-auto.tsv from mappings/required.tsv")
    parser.add_argument("--out", default=str(ASSETS))
    parser.add_argument("--index", default=str(INDEX))
    parser.add_argument("--lock", default=str(LOCK))
    parser.add_argument("--check", action="store_true", help="compare against the committed index, write nothing")
    parser.add_argument("--dry-run", action="store_true", help="resolve and report, write nothing")
    args = parser.parse_args(argv)

    root = Path(args.colloid_dir).expanduser().resolve()
    tree = ColloidTree(root)
    curated = read_table(MAPS / "colloid.tsv", "curated")
    auto = read_table(MAPS / "colloid-auto.tsv", "auto")

    if args.from_required:
        known = {(row.context, row.target) for row in curated}
        known_targets = {row.target for row in curated}
        # Places and file types keep their Material artwork, so a Colloid name
        # that would re-answer one of those is not harvested.
        material_names = read_names(MAPS / "places.tsv") | read_names(MAPS / "mimetypes.tsv")
        required = read_required(MAPS / "required.tsv")
        auto_rows: list[Row] = []
        for context, name in required:
            if context not in AUTO_CONTEXTS or (context, name) in known or name in known_targets:
                continue
            if name in material_names or name.removesuffix(SYMBOLIC_SUFFIX) in material_names:
                continue
            base = name[: -len(SYMBOLIC_SUFFIX)] if name.endswith(SYMBOLIC_SUFFIX) else name
            has_art = tree.art(context, name) is not None
            has_symbolic = name.endswith(SYMBOLIC_SUFFIX) and tree.symbolic(context, base) is not None
            if has_art or has_symbolic:
                auto_rows.append(Row(context, name, base, "auto"))
        text = [
            "# colloid-auto.tsv — GENERATED by tools/vendor-colloid-icons.py --from-required",
            "# Names the live desktop asks for (mappings/required.tsv) that Colloid artwork",
            "# answers directly.  Regenerate with `make vendor-colloid`; edits are lost.",
            "# Format: <context>\\t<desktop icon name>\\t<colloid icon name>",
            "",
        ]
        text += [f"{row.context}\t{row.target}\t{row.icon}" for row in auto_rows]
        write_text(MAPS / "colloid-auto.tsv", "\n".join(text) + "\n")
        print(f"colloid-auto.tsv: {len(auto_rows)} rows")
        auto = auto_rows

    rows = merge_rows(curated, auto)
    index, files, missing = build_plan(tree, rows, args.variant)
    print(f"resolved {len(index['icons'])} icons ({len(files)} artwork files) from {root}")

    if missing:
        print(f"unresolved ({len(missing)}):")
        for line in missing[:40]:
            print(f"  {line}")
        if len(missing) > 40:
            print(f"  … and {len(missing) - 40} more")

    if args.dry_run:
        for key in list(index["icons"])[:10]:
            print(f"  {key} -> {index['icons'][key]['source']}")
        return 1 if missing else 0

    out = Path(args.out).expanduser()
    if args.check:
        return check(out, index, files)

    write_assets(out, files, root)
    write_text(Path(args.index).expanduser(), dump_index(index))
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode("utf-8") + b"\0" + files[rel])
    lock = {
        "source": "Colloid-icon-theme",
        "variant": args.variant,
        "archive": "Colloid-icon-theme-2026-08-10",
        "index_theme_sha256": index["index_theme_sha256"],
        "src_svg": index["src_svg"],
        "vendored_icons": len(index["icons"]),
        "vendored_files": len(files),
        "sha256": digest.hexdigest(),
    }
    if args.lock:
        write_text(Path(args.lock).expanduser(), json.dumps(lock, indent=1, sort_keys=True) + "\n")
    print(f"assets: {out} ({len(files)} files)")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
