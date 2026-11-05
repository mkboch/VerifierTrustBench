#!/usr/bin/env bash
# B4 driver: finish the large phase, then serve and run small, then granite. Releases GPUs at the end.
set -u
ROOT=${VTB_ROOT:?set VTB_ROOT to the research tree root}
PY=${VTB_PYTHON:-python3}
RR=$ROOT/nature_extension/reviewer_response_20261016
log() { echo "[$(date +%H:%M:%S)] $*"; }

wait_for_pid() {
  while pgrep -f "run_ladder.py --phase $1" >/dev/null 2>&1; do sleep 20; done
}
wait_up() {   # port, timeout_s
  local t=0
  until curl -fsS --max-time 5 "http://127.0.0.1:$1/v1/models" >/dev/null 2>&1; do
    sleep 15; t=$((t+15)); [ $t -ge "$2" ] && { log "TIMEOUT waiting on port $1"; return 1; }
  done
  return 0
}

log "waiting for the large phase to finish"
wait_for_pid large
log "large phase done: $(wc -l < "$RR/ladder/ladder_trials.jsonl") records"

log "stopping large servers"
bash "$ROOT/exp3heldout/serve3.sh" stop-large >/dev/null 2>&1
sleep 20

log "starting small servers (qwen3_8 :8100, gemma4_12 :8102)"
nohup bash "$ROOT/exp3heldout/serve3.sh" start-small > "$RR/ladder/serve_small.log" 2>&1 &
if wait_up 8100 1800 && wait_up 8102 1800; then
  log "small servers ready; running small phase"
  $PY "$RR/code/run_ladder.py" --phase small >> "$RR/ladder/run_small.log" 2>&1
  log "small phase done: $(wc -l < "$RR/ladder/ladder_trials.jsonl") records"
else
  log "ERROR small servers did not come up"
fi
bash "$ROOT/exp3heldout/serve3.sh" stop-small >/dev/null 2>&1
sleep 20

log "starting granite server (:8104, TP4)"
nohup bash "$ROOT/exp3heldout/serve3.sh" start granite42_30 > "$RR/ladder/serve_granite.log" 2>&1 &
if wait_up 8104 2400; then
  log "granite ready; running granite phase"
  $PY "$RR/code/run_ladder.py" --phase granite >> "$RR/ladder/run_granite.log" 2>&1
  log "granite phase done: $(wc -l < "$RR/ladder/ladder_trials.jsonl") records"
else
  log "ERROR granite did not come up"
fi
bash "$ROOT/exp3heldout/serve3.sh" stop granite42_30 >/dev/null 2>&1
sleep 15
log "LADDER ALL PHASES COMPLETE: $(wc -l < "$RR/ladder/ladder_trials.jsonl") records"
nvidia-smi --query-gpu=index,memory.used --format=csv,noheader
