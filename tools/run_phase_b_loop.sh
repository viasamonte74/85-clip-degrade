#!/bin/sh
# Phase B driver: as masters arrive, prepare references (disk-saving mode: downloaded masters are
# deleted after the reference is re-verified), link references of groups that already have a split,
# and degrade them. New groups are allocated once the plan is complete (assign_splits.py --plan,
# run by hand), after which this loop degrades them too. Stop with: touch logs/phase_b.stop
cd "$(dirname "$0")/.." || exit 1
. .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
PLAN=${PLAN:-config/phase_b_clips.yaml}
while [ ! -e logs/phase_b.stop ]; do
  nice -n 19 python tools/prepare_references.py --plan $PLAN --kinds ${KINDS:-frames_http zip_j2k y4m_range ftp_mov_j2k commons_window blender} --drop-masters
  python tools/assign_splits.py --existing-only > /dev/null
  nice -n 19 python tools/generate_degradations.py --workers ${DEGRADE_WORKERS:-2} --variants-per-factor ${VPF:-2}
  R=$(python -c "from sn85ds.util import read_jsonl;print(len(read_jsonl('metadata/references.jsonl')))")
  V=$(python -c "from sn85ds.util import read_jsonl;print(len(read_jsonl('metadata/variants.jsonl')))")
  echo "$(date -u +%FT%TZ) references $R variants $V free $(df -BG --output=avail /workspace | tail -1)"
  sleep 120
done
