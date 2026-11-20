#!/bin/sh
# Phase B reference preparation loop (disk-saving mode). Runs beside run_phase_b_degrade_loop.sh;
# an exclusive lock keeps a single preparation pass at a time. Stop with: touch logs/phase_b.stop
cd "$(dirname "$0")/.." || exit 1
. .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
PLAN=${PLAN:-config/phase_b_clips.yaml}
[ -n "$WAIT_PID" ] && while kill -0 "$WAIT_PID" 2>/dev/null; do sleep 30; done
while [ ! -e logs/phase_b.stop ]; do
  flock logs/prepare.lock nice -n 19 python tools/prepare_references.py --plan $PLAN \
    --kinds ${KINDS:-frames_http zip_j2k y4m_range ftp_mov_j2k commons_window blender} --drop-masters
  echo "$(date -u +%FT%TZ) prepare pass done; references $(wc -l < metadata/references.jsonl); free $(df -BG --output=avail /workspace | tail -1)"
  sleep 120
done
