#!/usr/bin/env bash
# Install the user-level shared-mime-info override that keeps PDF and Markdown
# files on their own icon names (see mime/50-cinnamon-mosaic-mime-icons.xml).
#
#   ./scripts/install-mime-icons.sh              # install into ~/.local/share/mime
#   ./scripts/install-mime-icons.sh --dry-run    # print what would happen
#   ./scripts/install-mime-icons.sh --uninstall  # remove it again
#   ./scripts/install-mime-icons.sh --mime-dir DIR
#
# The override lives in the user MIME database, so no root access is needed and
# the system packages (e.g. /usr/share/mime/packages/obsidian.xml) are left
# untouched.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
NAME="50-cinnamon-mosaic-mime-icons.xml"
SRC="$REPO/mime/$NAME"
MIME_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/mime"
MODE=install
DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --mime-dir) MIME_ROOT="${2:?--mime-dir needs a path}"; shift 2 ;;
    --uninstall) MODE=uninstall; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

DEST="$MIME_ROOT/packages/$NAME"

if [ ! -f "$SRC" ]; then
  echo "override source missing: $SRC" >&2
  exit 1
fi

if command -v xmllint >/dev/null 2>&1; then
  xmllint --noout "$SRC" || { echo "override is not well-formed XML: $SRC" >&2; exit 1; }
fi

echo "source: $SRC"
echo "target: $DEST"

if [ "$DRY" = 1 ]; then
  echo "dry run, nothing written"
  exit 0
fi

if [ "$MODE" = uninstall ]; then
  rm -f "$DEST"
  echo "removed $DEST"
else
  mkdir -p "$MIME_ROOT/packages"
  install -m 0644 "$SRC" "$DEST"
  echo "installed $DEST"
fi

if ! command -v update-mime-database >/dev/null 2>&1; then
  echo "update-mime-database not found; install shared-mime-info and rerun" >&2
  exit 1
fi

# update-mime-database reports XML problems on stderr but still exits 0, so
# watch its output as well.
MIME_OUT="$(update-mime-database "$MIME_ROOT" 2>&1)" || {
  printf '%s\n' "$MIME_OUT" >&2
  echo "update-mime-database failed for $MIME_ROOT" >&2
  exit 1
}
if printf '%s\n' "$MIME_OUT" | grep -q "Failed to parse"; then
  printf '%s\n' "$MIME_OUT" >&2
  echo "mime database not updated: the override XML was rejected" >&2
  exit 1
fi
echo "mime database rebuilt: $MIME_ROOT"

cat <<'EOF'

Already running apps keep the icon names they cached at startup:
  nemo -q                      # Cinnamon file manager
  # or log out / back in
Check the result with:
  gio info -a standard::icon PATH/TO/file.pdf
EOF
