#!/usr/bin/env bash
# Experiment 2B-broad server orchestration (helpers copied from exp2b/orchestrate.sh; frozen launch commands per model).
#
#   exp2b/orchestrate.sh status
#   exp2b/orchestrate.sh stop-large       stop qwen38_27 (:8097) and qwen36_27 (:8098)
#   exp2b/orchestrate.sh start-small      qwen3_8 on GPU0 (:8100), llama31_8 on GPU1 (:8101)
#   exp2b/orchestrate.sh stop-small
#   exp2b/orchestrate.sh start-large      restore the original 27B services, original flags
#   exp2b/orchestrate.sh to-small         stop-large, then start-small
#   exp2b/orchestrate.sh to-large         stop-small, then start-large
#
# Safety: a process group is signalled only after its leader PID is confirmed to be a
# vLLM api_server bound to the expected port. Stopping waits for the port to close and
# for GPU memory on the relevant devices to drop below 1 GiB. Nothing else is killed.
set -euo pipefail

ROOT="${VTB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
VLLM_ENV="${VTB_VLLM_ENV:?set VTB_VLLM_ENV to your vLLM environment prefix}"
VLLM_PY="$VLLM_ENV/bin/python"
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
# vLLM JIT-compiles kernels at engine start and needs `ninja` from this environment. The
# original launcher put the environment on PATH; without it engine startup fails with
# FileNotFoundError: 'ninja' (observed in validation run exp2ar_validation_20260913_011452).
export PATH="$VLLM_ENV/bin:$PATH"
LOGDIR="$ROOT/logs/exp2bbroad"
PIDDIR="$ROOT/pids"
mkdir -p "$LOGDIR" "$PIDDIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
say() { echo "[$(ts)] $*"; }

health() { curl -fsS --max-time 5 "http://127.0.0.1:$1/v1/models" >/dev/null 2>&1; }

served() {
  curl -fsS --max-time 5 "http://127.0.0.1:$1/v1/models" 2>/dev/null |
    "$VLLM_PY" -c 'import sys,json; d=json.load(sys.stdin)["data"][0]; print(d["id"], d.get("root"), d.get("max_model_len"))' 2>/dev/null || echo "down"
}

listener_pid() {  # pid listening on port, or empty
  ss -ltnpH "sport = :$1" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1 || true
}

gpu_mem() {  # used MiB on one GPU index
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "$1" | tr -d ' '
}

wait_gpu_free() {  # gpus...
  for _ in $(seq 1 90); do
    local busy=0
    for g in "$@"; do
      if [ "$(gpu_mem "$g")" -ge 1024 ]; then busy=1; fi
    done
    [ "$busy" = 0 ] && { say "GPUs $* released"; return 0; }
    sleep 2
  done
  say "ERROR: GPUs $* still hold memory:"; nvidia-smi --query-gpu=index,memory.used --format=csv
  return 1
}

wait_up() {  # port name log
  local pid=""
  [ -f "$PIDDIR/$2.pid" ] && pid="$(cat "$PIDDIR/$2.pid")"
  for i in $(seq 1 600); do
    if health "$1"; then say "READY $2 on :$1 -> $(served "$1")"; return 0; fi
    # A server that has exited will never answer; fail now rather than at the timeout.
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      say "ERROR: $2 process $pid exited during startup"; tail -n 40 "$3" || true
      return 1
    fi
    if (( i % 30 == 0 )); then say "waiting for $2 on :$1 ($((i*2))s)"; fi
    sleep 2
  done
  say "ERROR: $2 did not come up on :$1"; tail -n 80 "$3" || true
  return 1
}

stop_one() {  # name port
  local name="$1" port="$2" pid="" args=""
  pid="$(listener_pid "$port")"
  if [ -z "$pid" ] && [ -f "$PIDDIR/$name.pid" ]; then pid="$(cat "$PIDDIR/$name.pid")"; fi
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    say "$name: nothing running on :$port"; rm -f "$PIDDIR/$name.pid"; return 0
  fi
  args="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  if [[ "$args" != *"vllm.entrypoints.openai.api_server"* || "$args" != *"--port $port"* ]]; then
    say "REFUSING to stop pid $pid for $name: not a vLLM api_server on :$port"
    say "  cmdline: $args"
    return 1
  fi
  local pgid; pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
  if [ "$pgid" != "$pid" ]; then
    say "REFUSING: pid $pid is not its own process-group leader (pgid $pgid)"; return 1
  fi
  say "STOP $name pgid=$pgid (:$port)"
  kill -TERM -- "-$pgid" 2>/dev/null || true
  for _ in $(seq 1 60); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  if kill -0 "$pid" 2>/dev/null; then
    say "$name still alive after 60s; SIGKILL process group $pgid"
    kill -KILL -- "-$pgid" 2>/dev/null || true
    sleep 3
  fi
  for _ in $(seq 1 30); do health "$port" || break; sleep 1; done
  rm -f "$PIDDIR/$name.pid"
  say "$name stopped"
}

launch() {  # name gpus port log args...
  local name="$1" gpus="$2" port="$3" log="$4"; shift 4
  if health "$port"; then say "$name already serving on :$port -> $(served "$port")"; return 0; fi
  say "START $name on GPU(s) $gpus port $port (log $log)"
  nohup setsid env CUDA_VISIBLE_DEVICES="$gpus" HF_HOME="$HF_HOME" TOKENIZERS_PARALLELISM=false ${CANDIDATE_ENV:-} \
    VLLM_WORKER_MULTIPROC_METHOD=spawn "$VLLM_PY" -m vllm.entrypoints.openai.api_server "$@" \
    > "$log" 2>&1 < /dev/null &
  echo $! > "$PIDDIR/$name.pid"
}

start_candidate() {  # name
  local stamp; stamp="$(date +%Y%m%d_%H%M%S)"; local name="$1"; local log="$LOGDIR/${name}_$stamp.log"
  # candidate compile caches on /scratch (/home is nearly full); production services keep their default cache
  CANDIDATE_ENV="VLLM_CACHE_ROOT=${VTB_VLLM_CACHE:-$HOME/.cache/vllm}"
  case "$name" in
    mistral_small32)
      launch "$name" "0,1,2,3" 8104 "$log" \
        --model mistralai/Mistral-Small-3.2-24B-Instruct-2506 --revision 95a6d26c4bfb886c58daf9d3f7332c857cb27b43 \
        --tokenizer-mode mistral --served-model-name "$name" --host 127.0.0.1 --port 8104 \
        --tensor-parallel-size 4 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching --limit-mm-per-prompt '{"image":0}' ;;
    olmo31_32)
      launch "$name" "0,1,2,3" 8104 "$log" \
        --model allenai/Olmo-3.1-32B-Instruct --revision ac0587e4a7744a551c059d8cd17ba220bc940dae \
        --served-model-name "$name" --host 127.0.0.1 --port 8104 \
        --tensor-parallel-size 4 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching ;;
    llama33_70awq)
      launch "$name" "0,1,2,3" 8104 "$log" \
        --model casperhansen/llama-3.3-70b-instruct-awq --revision 64d255621f40b42adaf6d1f32a47e1d4534c0f14 \
        --served-model-name "$name" --host 127.0.0.1 --port 8104 \
        --tensor-parallel-size 4 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching  ;;
    glm4_32)
      launch "$name" "0,1,2,3" 8104 "$log" \
        --model zai-org/GLM-4-32B-0414 --revision 077b5c2f5c43bd3239fd605a0600229e8facbd4a \
        --served-model-name "$name" --host 127.0.0.1 --port 8104 \
        --tensor-parallel-size 4 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching  ;;
    granite42_30)
      launch "$name" "0,1,2,3" 8104 "$log" \
        --model ibm-granite/granite-4.2-30b --revision 9e668ce1c538387ef24d3644e9b0606647762636 \
        --served-model-name "$name" --host 127.0.0.1 --port 8104 \
        --tensor-parallel-size 4 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching  ;;
    exaone45_33)
      launch "$name" "0,1,2,3" 8104 "$log" \
        --model LGAI-EXAONE/EXAONE-4.5-33B --revision 570aa4b15a4f45ba1133072b45f50198f6e3b4fd \
        --served-model-name "$name" --host 127.0.0.1 --port 8104 \
        --tensor-parallel-size 4 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching --language-model-only --skip-mm-profiling  ;;
    seedoss_36)
      launch "$name" "0,1,2,3" 8104 "$log" \
        --model ByteDance-Seed/Seed-OSS-36B-Instruct --revision 497f1dca95ebdec98e41d517b9f060ee753c902f \
        --served-model-name "$name" --host 127.0.0.1 --port 8104 \
        --tensor-parallel-size 4 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching  ;;
    gptoss_20)
      launch "$name" "0" 8104 "$log" \
        --model openai/gpt-oss-20b --revision 6cee5e81ee83917806bbde320786a8fb61efebee \
        --served-model-name "$name" --host 127.0.0.1 --port 8104 \
        --tensor-parallel-size 1 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching --reasoning-parser openai_gptoss  ;;
    *) say "unknown candidate $name"; return 2 ;;
  esac
  wait_up 8104 "$name" "$log"
}

start_large() {
  local stamp; stamp="$(date +%Y%m%d_%H%M%S)"
  launch qwen38_27 "0,1" 8097 "$LOGDIR/qwen38_27_$stamp.log" \
    --model cyankiwi/Qwen3.8-27B-AWQ-INT4 --served-model-name qwen38_27 --host 127.0.0.1 --port 8097 \
    --tensor-parallel-size 2 --gpu-memory-utilization 0.90 --max-model-len 65536 --max-num-seqs 2 \
    --enable-chunked-prefill --trust-remote-code --reasoning-parser qwen3
  launch qwen36_27 "2,3" 8098 "$LOGDIR/qwen36_27_$stamp.log" \
    --model QuantTrio/Qwen3.6-27B-AWQ --served-model-name qwen36_27 --host 127.0.0.1 --port 8098 \
    --tensor-parallel-size 2 --gpu-memory-utilization 0.90 --max-model-len 65536 --max-num-seqs 2 \
    --enable-chunked-prefill --trust-remote-code --reasoning-parser qwen3
  wait_up 8097 qwen38_27 "$LOGDIR/qwen38_27_$stamp.log"
  wait_up 8098 qwen36_27 "$LOGDIR/qwen36_27_$stamp.log"
}

stop_large() { stop_one qwen38_27 8097; stop_one qwen36_27 8098; wait_gpu_free 0 1 2 3; }

status() {
  for p in 8097 8098 8104; do echo ":$p $(served "$p") pid=$(listener_pid "$p")"; done
  nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader
}

case "${1:-status}" in
  status) status ;;
  stop-large) stop_large ;;
  start-large) start_large ;;
  start) start_candidate "${2:?name}" ;;
  stop) stop_one "${2:?name}" 8104; wait_gpu_free 0 1 2 3 ;;
  *) echo "unknown command $1"; exit 2 ;;
esac
