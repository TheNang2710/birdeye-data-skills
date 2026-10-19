#!/usr/bin/env bash
# Re-sync the bundled Birdeye CLI into deploy-vercel/api/_cli/.
#
# The bundle mixes two sources:
#   * ../birdeye-screener — the shared CLI + generic (non-ML) modules
#   * ./api/_ml/          — the secure ML runtime (independent master copy)
#
# Only the shared parts are copied. The ML runtime (junk_ml, trending_score,
# lr_params.json) lives in ./api/_ml/ and is loaded from there at runtime via
# the `modules` package shim, so it is never duplicated into the bundle.
#
#   ./sync-cli.sh          # copy
#   ./sync-cli.sh --check  # report drift / missing ML, exit 1 if out of sync
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/../birdeye-screener"
ML="$HERE/api/_ml"
DST="$HERE/api/_cli"

# Generic modules come from the shared workspace source.
MODULES=(contract_dd.py kline_pattern.py wallet_data.py)
# ML runtime is owned by ./api/_ml/ and must always be present.
REQUIRED_ML=(junk_ml.py trending_score.py lr_params.json)

check=0
[[ "${1:-}" == "--check" ]] && check=1

FILES=(
  "$SRC/scripts/birdeye_cli.py:$DST/scripts/birdeye_cli.py"
)
for m in "${MODULES[@]}"; do
  FILES+=("$SRC/scripts/modules/$m:$DST/scripts/modules/$m")
done

drift=0
for pair in "${FILES[@]}"; do
  s="${pair%%:*}"; d="${pair##*:}"
  if [[ ! -f "$s" ]]; then echo "MISSING SOURCE  $s" >&2; drift=1; continue; fi
  if [[ ! -f "$d" ]] || ! cmp -s "$s" "$d"; then
    if [[ $check -eq 1 ]]; then
      echo "DRIFT  $(basename "$d")"
      drift=1
    else
      mkdir -p "$(dirname "$d")"
      cp "$s" "$d"
      echo "synced  $(basename "$d")"
    fi
  fi
done

for f in "${REQUIRED_ML[@]}"; do
  if [[ ! -f "$ML/$f" ]]; then
    echo "MISSING ML  ml/$f" >&2
    drift=1
  fi
done

if [[ $check -eq 1 ]]; then
  [[ $drift -eq 0 ]] && echo "in sync"
  exit $drift
fi

if [[ $drift -eq 0 ]]; then echo "already in sync"; fi
