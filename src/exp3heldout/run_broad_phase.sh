#!/usr/bin/env bash
# Phase 4 driver: the 7 non-primary broad models, one at a time on :8104 (TP4).
# Per model: start -> wait healthy -> preflight (old dev papers) -> context gate -> broad phase -> stop.
# A gate failure SKIPS the model and is recorded; nothing is tuned to make a model pass.
set -u
cd "${VTB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RUN_DIR=runs/exp3heldout_20260918_014959
PY="${VTB_PYTHON:-python3}"
LOGD=exp3heldout/logs
STATUS=$LOGD/phase4_status.txt
MODELS="mistral_small32 olmo31_32 llama33_70awq gptoss_20 glm4_32 exaone45_33 seedoss_36"

say() { echo "$(date '+%F %T') $*" | tee -a $STATUS; }

say "PHASE4 START models: $MODELS"
exp3heldout/serve3.sh stop granite42_30 >> $LOGD/phase4_serve.log 2>&1
sleep 20

for m in $MODELS; do
  say "=== $m: starting server"
  nohup exp3heldout/serve3.sh start "$m" > $LOGD/serve_$m.log 2>&1 &
  # wait up to 40 min for health
  ok=0
  for i in $(seq 1 80); do
    sleep 30
    if curl -sf http://127.0.0.1:8104/v1/models >/dev/null 2>&1; then ok=1; break; fi
  done
  if [ $ok -ne 1 ]; then say "$m SKIP: server never became healthy"; exp3heldout/serve3.sh stop "$m" >> $LOGD/phase4_serve.log 2>&1; sleep 20; continue; fi
  say "$m: server healthy"

  if ! $PY exp3heldout/validate_pipeline.py --models "$m" > $LOGD/validate_$m.log 2>&1; then
    say "$m SKIP: preflight FAILED (see validate_$m.log) - not tuned, recorded"
    exp3heldout/serve3.sh stop "$m" >> $LOGD/phase4_serve.log 2>&1; sleep 20; continue
  fi
  say "$m: preflight pass"

  if ! $PY exp3heldout/context_gate.py --models "$m" > $LOGD/ctx_$m.log 2>&1; then
    say "$m SKIP: context gate FAILED (see ctx_$m.log)"
    exp3heldout/serve3.sh stop "$m" >> $LOGD/phase4_serve.log 2>&1; sleep 20; continue
  fi
  say "$m: context gate pass"

  $PY exp3heldout/run_heldout.py --run-dir $RUN_DIR --model "$m" --phases broad > $LOGD/run_$m.log 2>&1
  say "$m: $(grep -h DONE $LOGD/run_$m.log | tail -1)"

  exp3heldout/serve3.sh stop "$m" >> $LOGD/phase4_serve.log 2>&1
  sleep 20
done
say "PHASE4 COMPLETE"
