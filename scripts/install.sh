#!/usr/bin/env bash
# Install the Material-Cinnamon icon theme for the Cinnamon desktop.
#
#   ./scripts/install.sh                # copy to ~/.local/share/icons/Material-Cinnamon
#   ./scripts/install.sh --set           # ... and make it the active icon theme
#   ./scripts/install.sh --theme-dir DIR # copy into DIR/Material-Cinnamon instead
#   ./scripts/install.sh --dry-run       # print what would happen
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
NAME="Material-Cinnamon"
SRC="$REPO/dist/$NAME"
ICON_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/icons"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/material-cinnamon.previous"
DO_SET=0
DRY=0
NO_CACHE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --theme-dir) ICON_ROOT="${2:?--theme-dir needs a path}"; shift 2 ;;
    --set) DO_SET=1; shift ;;
    --no-cache) NO_CACHE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

DEST="$ICON_ROOT/$NAME"

if [ ! -d "$SRC" ]; then
  echo "build output missing: $SRC" >&2
  echo "run: make build" >&2
  exit 1
fi

if [ ! -f "$SRC/index.theme" ]; then
  echo "incomplete theme (no index.theme): $SRC" >&2
  exit 1
fi

echo "source:      $SRC"
echo "destination: $DEST"
if [ "$DRY" = 1 ]; then
  echo "dry run, nothing copied"
  exit 0
fi

mkdir -p "$ICON_ROOT"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "$SRC/" "$DEST/"
else
  rm -rf "$DEST"
  cp -a "$SRC" "$DEST"
fi
echo "copied $(find "$DEST" -type f | wc -l) files, $(find "$DEST" -type l | wc -l) symlinks"

if [ "$NO_CACHE" = 0 ] && command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -q "$DEST" && echo "icon cache rebuilt"
fi

if [ "$DO_SET" = 1 ]; then
  mkdir -p "$(dirname "$STATE")"
  gsettings get org.cinnamon.desktop.interface icon-theme 2>/dev/null | tr -d "'" > "$STATE" || true
  gsettings set org.cinnamon.desktop.interface icon-theme "$NAME"
  echo "active icon theme: $NAME (previous: $(cat "$STATE" 2>/dev/null || echo unknown))"
  echo "restart the desktop to apply everywhere: nemo -q; cinnamon --replace &"
else
  echo "activate it in Menu -> Preferences -> Themes -> Icons,"
  echo "or run: gsettings set org.cinnamon.desktop.interface icon-theme $NAME"
fi
