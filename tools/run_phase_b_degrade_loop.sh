#!/bin/sh
# Phase B degradation loop: link references of groups that have a split, then degrade what is missing.
# First pass: 1 variant per factor (one x2 + one x4 per original); once nothing is missing at 1, the second
# variant per factor (VPF_MAX, default 2 -> four variants per original). Recipes are fixed by seed, so the
# order changes no output. Workers: logs/degrade_workers if present (read at the start of every pass),
# else DEGRADE_WORKERS (default 1). Stop with: touch logs/phase_b.stop
cd "$(dirname "$0")/.." || exit 1
. .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
while [ ! -e logs/phase_b.stop ]; do
  python tools/assign_splits.py --existing-only > /dev/null
  W=$(cat logs/degrade_workers 2>/dev/null || echo "${DEGRADE_WORKERS:-1}")
  N1=$(python tools/generate_degradations.py --variants-per-factor 1 --dry-run 2>/dev/null | head -n 1 | cut -d' ' -f1)
  if [ "$N1" = "0" ]; then V=${VPF_MAX:-2}; else V=1; fi
  echo "$(date -u +%FT%TZ) degrade pass: variants-per-factor $V, workers $W"
  nice -n 19 python tools/generate_degradations.py --workers "$W" --variants-per-factor "$V"
  echo "$(date -u +%FT%TZ) degrade pass done; variants $(wc -l < metadata/variants.jsonl)"
  sleep 120
done
