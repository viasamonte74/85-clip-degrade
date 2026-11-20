#!/bin/sh
# Drive the pilot as masters arrive: prepare ready references, keep splits, degrade new ones.
# Stops when every planned clip has a reference and 4 variants. Logs to logs/pilot_loop.log.
cd "$(dirname "$0")/.." || exit 1
. .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
PLAN=config/pilot_clips.yaml
N=$(python -c "import yaml;print(len(yaml.safe_load(open('$PLAN'))['clips']))")
while :; do
  nice -n 19 python tools/prepare_references.py --plan $PLAN --kinds frames_http zip_j2k y4m_range blender
  python tools/assign_splits.py --plan $PLAN > /dev/null
  nice -n 19 python tools/generate_degradations.py --workers 2
  R=$(python -c "from sn85ds.util import read_jsonl;print(len(read_jsonl('metadata/references.jsonl')))")
  V=$(python -c "from sn85ds.util import read_jsonl;print(len(read_jsonl('metadata/variants.jsonl')))")
  echo "$(date -u +%FT%TZ) references $R/$N variants $V/$((N*4))"
  [ "$R" -ge "$N" ] && [ "$V" -ge "$((N*4))" ] && break
  sleep 120
done
