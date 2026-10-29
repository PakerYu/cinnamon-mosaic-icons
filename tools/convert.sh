#!/usr/bin/env bash
# Convert a vscode-material-icon-theme checkout into the PNG sources used by
# this repository (icons/file/*.png and icons/folder/*.png).
#
#   ./tools/convert.sh [--upstream DIR] [--out DIR] [--size 512] [--dark]
#
# The upstream checkout ships SVG icons only. This repository vendors the
# rasterised 512x512 PNGs so that building the theme needs nothing but Pillow.
#
# Requires Inkscape 1.x on PATH.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
UPSTREAM="${MATERIAL_ICON_THEME:-}"
OUT="$REPO/icons"
SIZE=512

while [ $# -gt 0 ]; do
  case "$1" in
    --upstream) UPSTREAM="${2:?--upstream needs a path}"; shift 2 ;;
    --out) OUT="${2:?--out needs a path}"; shift 2 ;;
    --size) SIZE="${2:?--size needs a number}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$UPSTREAM" ]; then
  echo "need an upstream checkout: --upstream DIR or MATERIAL_ICON_THEME" >&2
  exit 1
fi
if [ ! -d "$UPSTREAM/icons" ]; then
  echo "$UPSTREAM/icons not found (is this a vscode-material-icon-theme checkout?)" >&2
  exit 1
fi
if ! command -v inkscape >/dev/null 2>&1; then
  echo "inkscape is required to rasterise the SVG sources" >&2
  exit 1
fi

render() {
  local svg="$1" png="$2"
  mkdir -p "$(dirname "$png")"
  inkscape "$svg" --export-type=png --export-filename="$png" --export-width="$SIZE" >/dev/null 2>&1
}

count=0
for svg in "$UPSTREAM"/icons/*.svg; do
  base="$(basename "$svg" .svg)"
  case "$base" in
    folder-*) target="$OUT/folder/$base.png" ;;
    *)        target="$OUT/file/$base.png" ;;
  esac
  render "$svg" "$target"
  count=$((count + 1))
done

echo "rendered $count icons at ${SIZE}x${SIZE} into $OUT"
echo "note: icons/folder-base.svg (used to synthesise the plain folder icon) is vendored in assets/"
