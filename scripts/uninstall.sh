#!/usr/bin/env bash
# Remove the Cinnamon-Mosaic icon theme and restore the previous icon theme.
#
#   ./scripts/uninstall.sh                # remove, restore previously active theme
#   ./scripts/uninstall.sh --theme-dir DIR
#   ./scripts/uninstall.sh --keep-active  # remove files only, leave gsettings alone
set -euo pipefail

NAME="Cinnamon-Mosaic"
ICON_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/icons"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/cinnamon-mosaic.previous"
KEEP_ACTIVE=0
DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --theme-dir) ICON_ROOT="${2:?--theme-dir needs a path}"; shift 2 ;;
    --keep-active) KEEP_ACTIVE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,7p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

DEST="$ICON_ROOT/$NAME"
CURRENT="$(gsettings get org.cinnamon.desktop.interface icon-theme 2>/dev/null | tr -d "'" || true)"
PREVIOUS="$(cat "$STATE" 2>/dev/null || echo Mint-Y)"

echo "theme:    $DEST"
echo "current:  ${CURRENT:-unknown}"
echo "previous: ${PREVIOUS:-unknown}"
if [ "$DRY" = 1 ]; then
  echo "dry run, nothing removed"
  exit 0
fi

if [ "$KEEP_ACTIVE" = 0 ] && [ "$CURRENT" = "$NAME" ]; then
  gsettings set org.cinnamon.desktop.interface icon-theme "${PREVIOUS:-Mint-Y}"
  echo "icon theme restored to ${PREVIOUS:-Mint-Y}"
fi

if [ -d "$DEST" ]; then
  rm -rf "$DEST"
  echo "removed $DEST"
else
  echo "nothing to remove"
fi
echo "restart the desktop if the change is not visible yet: nemo -q; cinnamon --replace &"
