#!/bin/bash
#
# Apply the cuttlefish-wearables patch series onto an AOSP checkout created from
# this repo's manifest (default.xml). Run it from the ROOT of that checkout:
#
#   cd <aosp-checkout-root>
#   /path/to/cuttlefish-wearables/apply.sh
#
# Each repo's patches are applied in numeric order with `git am`. On failure it
# stops so you can resolve, then re-run `git am --continue` / `--skip` and rerun.
#
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PATCHES="$HERE/patches"
AOSP_ROOT="${1:-$PWD}"
cd "$AOSP_ROOT" || { echo "cannot cd to $AOSP_ROOT"; exit 1; }

fail=0
# leaf dirs that directly contain *.patch, longest paths sorted naturally
for pdir in $(find "$PATCHES" -name '*.patch' -print0 | xargs -0 -n1 dirname | sort -u); do
  repo="${pdir#$PATCHES/}"
  if [ ! -d "$repo/.git" ] && [ ! -e "$repo/.git" ]; then
    echo "!! SKIP $repo (not in checkout)"; fail=1; continue
  fi
  echo "== git am: $repo =="
  if ! git -C "$repo" am "$pdir"/*.patch; then
    echo "!! git am FAILED in $repo — resolve, then: (cd $repo && git am --continue), then re-run"
    exit 1
  fi
done
[ "$fail" -eq 0 ] && echo "All patch series applied cleanly." || echo "Done with warnings (see SKIP lines)."
