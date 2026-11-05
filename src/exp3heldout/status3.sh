#!/usr/bin/env bash
cd "${VTB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RD=$(readlink -f runs/exp3heldout_latest)
echo "time $(date +%H:%M:%S)  disk $(df -h /scratch | awk 'NR==2{print $4}')"
for f in "$RD"/*_trials.jsonl; do [ -e "$f" ] && printf "%s %s\n" "$(basename $f)" "$(wc -l < $f)"; done
for m in qwen38_27 qwen36_27 qwen3_8 gemma4_12 granite42_30 mistral_small32 olmo31_32 llama33_70awq gptoss_20 glm4_32 exaone45_33 seedoss_36; do
  [ -f exp3heldout/logs/run_$m.log ] && echo "$m: $(grep -c ' -> ' exp3heldout/logs/run_$m.log) done $(grep -c 'DONE' exp3heldout/logs/run_$m.log)"
done
exit 0
