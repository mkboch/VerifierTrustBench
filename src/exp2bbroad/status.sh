#!/usr/bin/env bash
cd "${VTB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
echo "time $(date +%H:%M:%S)  disk $(df -h /scratch | awk 'NR==2{print $4}')"
grep -E "=== |ALL MODELS" exp2bbroad/logs/drive.log | tail -3
for f in runs/exp2bbroad_latest/*_trials.jsonl; do printf "%s %s\n" "$(basename $f)" "$(wc -l < $f)"; done
for m in gptoss_20 mistral_small32 granite42_30 exaone45_33 seedoss_36 glm4_32 olmo31_32 llama33_70awq; do
  [ -f exp2bbroad/logs/run_$m.log ] && echo "$m: $(grep -c ' -> OK' exp2bbroad/logs/run_$m.log) ok, $(grep DONE exp2bbroad/logs/run_$m.log | tail -1)"
done
