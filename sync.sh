#!/usr/bin/env bash
# micro (indentwrap build) sync — the whole procedure, executable. Repo: ejumper/micro.
#
# Installs:
#   desktop (source of truth)  ~/.config/micro   sync.sh push
#   server (bigboy)            ~/.config/micro   sync.sh pull
#
# Machine-local files are exactly the untracked ones (see .gitignore):
# buffers/, backups/, plug/, colorschemes/alts.micro. No command here can
# touch them.
#
# `pull` rebuilds the binary when the pull changed anything under patches/ or
# the build script — the binary is built per machine and never synced.
# Syntax, colorscheme, settings and bindings changes need no rebuild; micro
# reads them at startup.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "refusing to run as root: it would leave root-owned files in ~/.config/micro" >&2
  exit 1
fi

cd "$(dirname "$(readlink -f "$0")")"
git remote get-url origin | grep -q 'ejumper/micro\.git$' || {
  echo "not the micro repo — refusing to sync" >&2
  exit 1
}

case "${1:-}" in
  push)
    git add -A
    if git diff --cached --quiet; then
      echo "nothing to commit."
    else
      git commit -m "${2:-sync: $(hostname) $(date +%Y-%m-%d)}"
    fi
    git push origin main
    ;;

  pull)
    # micro rewrites settings.json when options change at runtime; the local
    # copy is never authoritative on pull-mode installs.
    git checkout -- settings.json 2>/dev/null || true

    OLD=$(git rev-parse HEAD)
    git pull --ff-only origin main

    if [ "$(git rev-parse HEAD)" = "$OLD" ]; then
      echo "already up to date."
    elif git diff --name-only "$OLD" HEAD -- patches build-micro-indentwrap.sh | grep -q .; then
      echo "patches/build script changed — rebuilding (~1-2 min)..."
      bash ./build-micro-indentwrap.sh
      echo "rebuild done — consider: python3 verify-softline-homeend.py"
    else
      echo "config-only update (no rebuild needed — micro reads these at startup)."
    fi
    ;;

  *)
    echo "usage: $(basename "$0") push [message] | pull" >&2
    exit 1
    ;;
esac
