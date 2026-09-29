#!/usr/bin/env bash
# Update progress.json for a benchmark run.
# Usage: update-progress.sh <report_dir> <step_id> <action>
#   report_dir  — path to the report folder containing progress.json
#   step_id     — integer 1..total_steps from progress.json
#   action      — start | complete | fail | skip

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <report_dir> <step_id> <start|complete|fail|skip>" >&2
  exit 1
fi

REPORT_DIR="$1"
STEP_ID="$2"
ACTION="$3"
PROGRESS_FILE="$REPORT_DIR/progress.json"

if [[ ! -f "$PROGRESS_FILE" ]]; then
  echo "Error: $PROGRESS_FILE not found" >&2
  exit 1
fi

if ! [[ "$STEP_ID" =~ ^[0-9]+$ ]]; then
  echo "Error: step_id must be an integer" >&2
  exit 1
fi

case "$ACTION" in
  start|complete|fail|skip) ;;
  *)
    echo "Error: action must be one of: start, complete, fail, skip" >&2
    exit 1
    ;;
esac

python3 - "$PROGRESS_FILE" "$STEP_ID" "$ACTION" <<'PYEOF'
import json, os, sys
from datetime import datetime, timezone

path, step_id, action = sys.argv[1], int(sys.argv[2]), sys.argv[3]
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

with open(path) as f:
    data = json.load(f)

matches = [s for s in data["steps"] if s["id"] == step_id]
if len(matches) != 1:
    sys.exit(f"Error: step_id must be between 1 and {data['total_steps']}, got {step_id}")
step = matches[0]

if action == "start":
    step["status"] = "in_progress"
    step["started_at"] = now
    data["current_step"] = step_id
    data["updated_at"] = now
elif action == "complete":
    step["status"] = "completed"
    step["completed_at"] = now
    data["updated_at"] = now
    if step_id == data["total_steps"]:
        data["status"] = "completed"
elif action == "fail":
    step["status"] = "failed"
    data["status"] = "failed"
    data["updated_at"] = now
elif action == "skip":
    step["status"] = "skipped"
    data["updated_at"] = now

tmp = f"{path}.tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
os.replace(tmp, path)

print(f"progress.json: step {step_id} -> {action}")
PYEOF
