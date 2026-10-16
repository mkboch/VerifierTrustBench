#!/usr/bin/env bash
# Development B session: qwen3_8 (GPU0 :8100) stays up; non-Qwen candidates rotate on GPUs 2,3 :8102.
# Restores the original 27B services at the end or on any failure.
set -uo pipefail
ROOT="${VTB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"; PY="${VTB_PYTHON:-python3}"; ORCH=$ROOT/exp2b/orchestrate.sh
LOG=$ROOT/exp2b/logs/bakeoff_small.log; cd $ROOT
say() { echo "[$(date '+%F %T')] $*" | tee -a $LOG; }
restore() { say "restore 27B"; $ORCH stop-qwen3_8 >>$LOG 2>&1; for m in gemma4_12 gemma4_26a4 ministral3_14; do $ORCH stop-nonqwen $m >>$LOG 2>&1; done; $ORCH start-large >>$LOG 2>&1; $ORCH status | tee -a $LOG; }
trap 'say "interrupted"; restore; exit 1' INT TERM
say "stop 27B"; $ORCH stop-large >>$LOG 2>&1 || { say "stop-large failed"; restore; exit 1; }
$ORCH start-qwen3_8 >>$LOG 2>&1 || { say "qwen3_8 failed to start"; restore; exit 1; }
first=1
for cand in gemma4_12 gemma4_26a4 ministral3_14; do
  say "START candidate $cand"
  if ! $ORCH start-nonqwen $cand >>$LOG 2>&1; then say "CANDIDATE $cand FAILED TO START (recorded as infeasible)"; $ORCH stop-nonqwen $cand >>$LOG 2>&1; continue; fi
  if [ $first = 1 ]; then models="qwen3_8 $cand"; first=0; else models="$cand"; fi
  $PY exp2b/dev/bakeoff.py run --models $models >>$LOG 2>&1; say "run $models exit=$?"
  $PY exp2b/dev/bakeoff.py probe --models $models >>$LOG 2>&1; say "probe $models exit=$?"
  $ORCH stop-nonqwen $cand >>$LOG 2>&1
done
say "done candidates"; restore; say "SMALL BAKEOFF DONE"
