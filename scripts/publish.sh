#!/usr/bin/env bash
# Publish this directory as a fresh git repository.
#
#   ./scripts/publish.sh --remote git@github.com:<you>/cinnamon-material-icons.git
#   ./scripts/publish.sh --remote ... --dry-run   # print the commands only
#
# Nothing is pushed without an explicit --yes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
REMOTE=""
BRANCH="main"
DRY=1
YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --remote) REMOTE="${2:?--remote needs a URL}"; shift 2 ;;
    --branch) BRANCH="${2:?--branch needs a name}"; shift 2 ;;
    --yes) YES=1; DRY=0; shift ;;
    --dry-run) DRY=1; YES=0; shift ;;
    -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[ -n "$REMOTE" ] || { echo "need --remote (e.g. git@github.com:you/repo.git)" >&2; exit 2; }

run() {
  echo "+ $*"
  if [ "$DRY" = 0 ]; then
    "$@"
  fi
}

cd "$REPO"
[ -d .git ] || run git init -b "$BRANCH"
run git add -A
run git commit -m "chore: initial import (material icon theme for Cinnamon)"
run git remote add origin "$REMOTE"
run git push -u origin "$BRANCH"

if [ "$DRY" = 1 ]; then
  echo
  echo "dry run; re-run with --yes to execute"
fi
