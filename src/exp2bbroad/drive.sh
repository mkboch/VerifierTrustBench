#!/usr/bin/env bash
# Sequential broad-family driver:  exp2bbroad/drive.sh <run-dir> <model> [<model> ...]
# For each model: start its frozen server on :8104 -> technical preflight (gate) -> full frozen run -> stop server.
# A model that fails the TECHNICAL gate is recorded and skipped; scientific weakness never stops a run.
# The production 27B services are stopped once at the start and restored by the caller (or `serve_broad.sh start-large`).
set -uo pipefail
ROOT="${VTB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PY="${VTB_PYTHON:-python3}"
RD="$1"; shift
mkdir -p "$ROOT/exp2bbroad/results"
say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if curl -fsS --max-time 5 http://127.0.0.1:8097/v1/models >/dev/null 2>&1; then
  say "stopping production services for candidate GPUs"
  "$ROOT/exp2bbroad/serve_broad.sh" stop-large
fi

for m in "$@"; do
  say "=== $m: starting server"
  if ! "$ROOT/exp2bbroad/serve_broad.sh" start "$m"; then
    say "$m: SERVER FAILED TO START (technical exclusion)"
    echo "{\"model\": \"$m\", \"gate_pass\": false, \"reason\": \"server failed to start\"}" > "$ROOT/exp2bbroad/results/preflight_$m.json"
    "$ROOT/exp2bbroad/serve_broad.sh" stop "$m" || true
    continue
  fi
  say "=== $m: preflight"
  if $PY "$ROOT/exp2bbroad/preflight_broad.py" --model "$m" >> "$ROOT/exp2bbroad/logs/preflight_$m.log" 2>&1; then
    say "=== $m: preflight PASS -> full run"
    $PY "$ROOT/exp2bbroad/run_broad.py" --run-dir "$RD" --model "$m" >> "$ROOT/exp2bbroad/logs/run_$m.log" 2>&1
    say "=== $m: run exit $?"
  else
    say "=== $m: preflight FAILED (technical) -> skipping scientific run"
  fi
  "$ROOT/exp2bbroad/serve_broad.sh" stop "$m"
  say "=== $m: done"
done
say "ALL MODELS DONE"
