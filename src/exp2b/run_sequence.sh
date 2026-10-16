#!/usr/bin/env bash
# Experiment 2B: run a scope through both phases, unattended and resumably.
#   exp2b/run_sequence.sh <run_dir> <validation|full>
# large (27B serving) -> swap to qwen3_8 + non-Qwen -> small -> restore 27B -> evaluate.
# Any failure restores the original 27B services before exiting. Re-running resumes.
set -uo pipefail
RUN_DIR="${1:?run dir}"; SCOPE="${2:?validation|full}"
ROOT="${VTB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"; PY="${VTB_PYTHON:-python3}"; ORCH=$ROOT/exp2b/orchestrate.sh
cd $ROOT; mkdir -p "$RUN_DIR/logs"; LOG="$RUN_DIR/logs/sequence.log"
NQ=$($PY -c "import sys; sys.path.insert(0,'exp2b'); import design as D; print(D.NONQWEN or '')")
say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
restore() { say "restoring 27B"; $ORCH stop-qwen3_8 >>"$LOG" 2>&1; [ -n "$NQ" ] && $ORCH stop-nonqwen "$NQ" >>"$LOG" 2>&1; $ORCH start-large >>"$LOG" 2>&1; $ORCH status | tee -a "$LOG"; }
phase() { say "PHASE $1 start"; $PY exp2b/run_exp2b.py --run-dir "$RUN_DIR" --scope "$SCOPE" --phase "$1" >> "$RUN_DIR/logs/phase_$1.log" 2>&1; local rc=$?; say "PHASE $1 exit=$rc ($(tail -n 1 "$RUN_DIR/logs/phase_$1.log"))"; return $rc; }
probe() { [ "$SCOPE" = validation ] || return 0; $PY exp2b/determinism_probe.py --run-dir "$RUN_DIR" --models "$@" >> "$LOG" 2>&1; say "probe $* exit=$?"; }
say "SEQUENCE start scope=$SCOPE run_dir=$RUN_DIR nonqwen=$NQ"; $ORCH status | tee -a "$LOG"
if ! curl -fsS --max-time 5 http://127.0.0.1:8097/v1/models >/dev/null || ! curl -fsS --max-time 5 http://127.0.0.1:8098/v1/models >/dev/null; then
  say "27B not serving; starting"; restore
fi
phase large || { restore; exit 1; }
probe qwen38_27 qwen36_27
say "swap to small"; $ORCH stop-large >>"$LOG" 2>&1 || { restore; exit 1; }
$ORCH start-qwen3_8 >>"$LOG" 2>&1 || { restore; exit 1; }
if [ -n "$NQ" ]; then $ORCH start-nonqwen "$NQ" >>"$LOG" 2>&1 || { restore; exit 1; }; fi
phase small || { restore; exit 1; }
probe qwen3_8 $NQ
restore
say "evaluating"; $PY exp2b/evaluate.py --run-dir "$RUN_DIR" > "$RUN_DIR/logs/evaluate.log" 2>&1; say "evaluate exit=$?"
$ORCH status | tee -a "$LOG"; say "SEQUENCE done"
