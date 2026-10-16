#!/usr/bin/env bash
# Phase 4b (amendment A3): re-run the broad phase so the 60 blind E0 audits per model are actually issued.
# The 180 targeted records per model already exist and are skipped by key. gptoss_20 is included so its preflight
# failure can be diagnosed with the full record preserved.
set -u
cd "${VTB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RUN_DIR=runs/exp3heldout_20260918_014959
PY="${VTB_PYTHON:-python3}"
LOGD=exp3heldout/logs
STATUS=$LOGD/phase4b_status.txt
MODELS="mistral_small32 olmo31_32 llama33_70awq glm4_32 exaone45_33 seedoss_36 gptoss_20"

say() { echo "$(date '+%F %T') $*" | tee -a $STATUS; }

say "PHASE4B START models: $MODELS"
for m in $MODELS; do
  say "=== $m: starting server"
  nohup exp3heldout/serve3.sh start "$m" > $LOGD/serve4b_$m.log 2>&1 &
  ok=0
  for i in $(seq 1 80); do
    sleep 30
    if curl -sf http://127.0.0.1:8104/v1/models >/dev/null 2>&1; then ok=1; break; fi
  done
  if [ $ok -ne 1 ]; then say "$m SKIP: server never became healthy"; exp3heldout/serve3.sh stop "$m" >> $LOGD/phase4b_serve.log 2>&1; sleep 20; continue; fi
  say "$m: server healthy"

  # preflight, keeping a per-model copy of the full record (validation_dev.json is overwritten per invocation)
  $PY exp3heldout/validate_pipeline.py --models "$m" > $LOGD/validate4b_$m.log 2>&1
  pf=$?
  cp exp3heldout/validation_dev.json $LOGD/validation_dev_$m.json 2>/dev/null
  if [ $pf -ne 0 ]; then
    say "$m SKIP: preflight FAILED (full record in validation_dev_$m.json) - not tuned, recorded"
    exp3heldout/serve3.sh stop "$m" >> $LOGD/phase4b_serve.log 2>&1; sleep 20; continue
  fi
  say "$m: preflight pass"

  $PY exp3heldout/run_heldout.py --run-dir $RUN_DIR --model "$m" --phases broad > $LOGD/run4b_$m.log 2>&1
  say "$m: $(grep -h DONE $LOGD/run4b_$m.log | tail -1)"

  exp3heldout/serve3.sh stop "$m" >> $LOGD/phase4b_serve.log 2>&1
  sleep 20
done
say "PHASE4B COMPLETE"
