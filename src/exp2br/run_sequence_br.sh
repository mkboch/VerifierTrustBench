#!/usr/bin/env bash
# Experiment 2B-R: blind-only sequence.  exp2br/run_sequence_br.sh <run_dir> <validation|full>
# large (27B) -> swap to qwen3_8 + gemma4_12 -> small -> restore 27B -> evaluate. Restores 27B on any failure. Resumable.
set -uo pipefail
RUN_DIR="${1:?}"; SCOPE="${2:?}"
ROOT="${VTB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"; PY="${VTB_PYTHON:-python3}"; ORCH=$ROOT/exp2b/orchestrate.sh; NQ=gemma4_12
cd $ROOT; mkdir -p "$RUN_DIR/logs"; LOG="$RUN_DIR/logs/sequence.log"
say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
restore() { say "restoring 27B"; $ORCH stop-qwen3_8 >>"$LOG" 2>&1; $ORCH stop-nonqwen $NQ >>"$LOG" 2>&1; $ORCH start-large >>"$LOG" 2>&1; $ORCH status | tee -a "$LOG"; }
phase() { say "PHASE $1 start"; $PY exp2br/run_exp2br.py --run-dir "$RUN_DIR" --scope "$SCOPE" --phase "$1" >> "$RUN_DIR/logs/phase_$1.log" 2>&1; local rc=$?; say "PHASE $1 exit=$rc ($(tail -n 1 "$RUN_DIR/logs/phase_$1.log"))"; return $rc; }
probe() { [ "$SCOPE" = validation ] || return 0; $PY exp2br/determinism_probe_br.py --run-dir "$RUN_DIR" --models "$@" >> "$LOG" 2>&1; say "probe $* exit=$?"; }
say "SEQUENCE start scope=$SCOPE"; $ORCH status | tee -a "$LOG"
if ! curl -fsS --max-time 5 http://127.0.0.1:8097/v1/models >/dev/null || ! curl -fsS --max-time 5 http://127.0.0.1:8098/v1/models >/dev/null; then restore; fi
phase large || { restore; exit 1; }
probe qwen38_27 qwen36_27
say "swap to small"; $ORCH stop-large >>"$LOG" 2>&1 || { restore; exit 1; }
$ORCH start-qwen3_8 >>"$LOG" 2>&1 || { restore; exit 1; }
$ORCH start-nonqwen $NQ >>"$LOG" 2>&1 || { restore; exit 1; }
phase small || { restore; exit 1; }
probe qwen3_8 $NQ
restore
say "evaluating"; $PY exp2br/evaluate_br.py --run-dir "$RUN_DIR" > "$RUN_DIR/logs/evaluate.log" 2>&1; say "evaluate exit=$?"
$ORCH status | tee -a "$LOG"; say "SEQUENCE done"
