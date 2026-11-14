#!/usr/bin/env bash
# Update everything on the home server in one go:
#   1) Second Brain (this repo)  → deploy/update.sh (git pull → backup → build → restart → /healthz/, rollback)
#   2) Link2Note bot (if cloned next to it, default ~/link2note) → its deploy/update.sh
# Usage:  ~/second_brain_ai/deploy/update-all.sh [--force]
#         or after `sudo ln -sf ~/second_brain_ai/deploy/update-all.sh /usr/local/bin/update-all`: update-all
set -Eeuo pipefail
here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
sb_dir="$(dirname "$here")"
l2n_dir="${LINK2NOTE_DIR:-$HOME/link2note}"
status=0

echo "=== Second Brain: $sb_dir ==="
bash "$sb_dir/deploy/update.sh" "$@" || status=1

if [ -f "$l2n_dir/deploy/update.sh" ]; then
    echo
    echo "=== Link2Note: $l2n_dir ==="
    (cd "$l2n_dir" && bash ./deploy/update.sh) || status=1
else
    echo "Link2Note not found in $l2n_dir (set LINK2NOTE_DIR=...) — skipped"
fi

echo
if [ "$status" -eq 0 ]; then echo "ALL OK"; else echo "SOMETHING FAILED — see the output above"; fi
exit "$status"
