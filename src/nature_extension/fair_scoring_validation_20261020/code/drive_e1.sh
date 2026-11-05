#!/usr/bin/env bash
# Drive the remaining E1 open-weight phases, swapping servers between phases.
#
# NOTE: an earlier version of this script waited on `pgrep -f run_e1_openweight.py`.
# That deadlocked, because the shell that launched the script carried the script's own
# text — including that pattern — in its command line, so the pgrep always matched itself.
# There is no wait here: the caller is responsible for ensuring no run is in flight.
#
# Resumable: run_e1_openweight.py skips any cell already recorded OK, so re-running this
# script after an interruption costs nothing. Never touches a frozen run.
set -u
ROOT=${VTB_ROOT:?set VTB_ROOT to the research tree root}
PH=$ROOT/nature_extension/fair_scoring_validation_20261020
PY=${VTB_PYTHON:-python3}
SERVE=$ROOT/exp3heldout/serve3.sh
log() { echo "[$(date +%H:%M:%S)] $*"; }
n() { wc -l < "$PH/e1/e1_openweight_trials.jsonl"; }

log "starting with $(n)/600 records"

log "stop-large"
"$SERVE" stop-large >>"$PH/e1/serve.log" 2>&1

log "start-small"
if ! "$SERVE" start-small >>"$PH/e1/serve.log" 2>&1; then
  log "start-small FAILED; see e1/serve.log"; exit 2
fi
log "running small phase (qwen3_8, gemma4_12)"
"$PY" "$PH/code/run_e1_openweight.py" --phase small >>"$PH/e1/run_small.log" 2>&1
log "small done: $(n)/600"

log "stop-small"
"$SERVE" stop-small >>"$PH/e1/serve.log" 2>&1

log "start granite42_30"
if ! "$SERVE" start granite42_30 >>"$PH/e1/serve.log" 2>&1; then
  log "start granite FAILED; see e1/serve.log"; exit 2
fi
log "running granite phase"
"$PY" "$PH/code/run_e1_openweight.py" --phase granite >>"$PH/e1/run_granite.log" 2>&1
log "granite done: $(n)/600"

log "stop granite42_30"
"$SERVE" stop granite42_30 >>"$PH/e1/serve.log" 2>&1

log "ALL E1 OPEN-WEIGHT PHASES COMPLETE: $(n)/600"
