#!/usr/bin/env bash
# Fetch the upstream vscode-material-icon-theme checkout pinned in
# upstream.lock.json into vendor/ (used by `make refresh-maps` and tools/convert.sh).
#
#   ./scripts/fetch-upstream.sh [--ref TAG] [--force]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
DEST="$REPO/vendor/vscode-material-icon-theme"
LOCK="$REPO/upstream.lock.json"
REF=""
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF="${2:?--ref needs a tag}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,8p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$REF" ]; then
  REF="$(python3 -c "import json;print(json.load(open('$LOCK'))['tag'])")"
fi
URL="https://codeload.github.com/material-extensions/vscode-material-icon-theme/tar.gz/refs/tags/$REF"

if [ -d "$DEST" ] && [ "$FORCE" = 0 ]; then
  echo "$DEST already exists (use --force to refetch)"
  exit 0
fi

echo "fetching $REF"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$URL" -o "$TMP/upstream.tar.gz"
tar -xzf "$TMP/upstream.tar.gz" -C "$TMP"
SRC="$(find "$TMP" -maxdepth 1 -type d -name 'vscode-material-icon-theme-*' | head -1)"
[ -n "$SRC" ] || { echo "unexpected archive layout" >&2; exit 1; }

rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
mv "$SRC" "$DEST"
echo "upstream $REF -> $DEST"
echo "next: make refresh-maps   # or: ./tools/convert.sh --upstream $DEST"
