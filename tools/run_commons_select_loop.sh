#!/bin/sh
# Re-run tools/commons_select.py every 20 minutes until every accepted Commons file is resolved
# (planned, or rejected by the automatic checks). Downloads that Wikimedia rate-limits are deferred.
cd "$(dirname "$0")/.." || exit 1
. .venv/bin/activate
while :; do
  nice -n 19 python tools/commons_select.py >> logs/commons_select.log 2>&1
  LEFT=$(python - <<'PY'
import yaml
from sn85ds.util import read_jsonl
acc = [k for k, v in yaml.safe_load(open("config/commons_review.yaml"))["files"].items() if v["decision"] == "accept"]
plan = open("config/phase_b_clips.yaml").read()
rej = {r["review_id"] for r in read_jsonl("metadata/commons_review.jsonl") if r.get("decision") == "reject"}
print(sum(1 for k in acc if f"cam_wc_{k}" not in plan and k not in rej))
PY
)
  echo "$(date -u +%FT%TZ) accepted files still unresolved: $LEFT" >> logs/commons_select.log
  [ "$LEFT" -eq 0 ] && break
  sleep 1800
done
