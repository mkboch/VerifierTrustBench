#!/usr/bin/env bash
# Experiment 2B server orchestration (from exp2b/orchestrate.sh; adds the non-Qwen verifier on GPUs 2,3 :8102).
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
LOGDIR="$ROOT/logs/exp2b"
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
  nohup setsid env CUDA_VISIBLE_DEVICES="$gpus" HF_HOME="$HF_HOME" TOKENIZERS_PARALLELISM=false \
    VLLM_WORKER_MULTIPROC_METHOD=spawn "$VLLM_PY" -m vllm.entrypoints.openai.api_server "$@" \
    > "$log" 2>&1 < /dev/null &
  echo $! > "$PIDDIR/$name.pid"
}

start_large() {
  local stamp; stamp="$(date +%Y%m%d_%H%M%S)"
  # Identical to the original service command lines recorded in INITIAL_STATE.md.
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

start_small() {
  local stamp; stamp="$(date +%Y%m%d_%H%M%S)"
  # Prefix caching is disabled on the temporary 8B servers. vLLM already disables it for the
  # hybrid 27B architecture; with it enabled on the 8B models an identical retry was served
  # from a warm cache and diverged from the cold original at temperature 0 (validation run
  # exp2ar_validation_20260913_014118), so a replicate arm would measure cache effects
  # rather than the noise the exposure arms face. All four models now compute every request
  # uncached.
  launch qwen3_8 "0" 8100 "$LOGDIR/qwen3_8_$stamp.log" \
    --model Qwen/Qwen3-8B --served-model-name qwen3_8 --host 127.0.0.1 --port 8100 \
    --tensor-parallel-size 1 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
    --enable-chunked-prefill --no-enable-prefix-caching --trust-remote-code --reasoning-parser qwen3
  launch llama31_8 "1" 8101 "$LOGDIR/llama31_8_$stamp.log" \
    --model meta-llama/Llama-3.1-8B-Instruct --served-model-name llama31_8 --host 127.0.0.1 --port 8101 \
    --tensor-parallel-size 1 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
    --enable-chunked-prefill --no-enable-prefix-caching --trust-remote-code
  wait_up 8100 qwen3_8 "$LOGDIR/qwen3_8_$stamp.log"
  wait_up 8101 llama31_8 "$LOGDIR/llama31_8_$stamp.log"
}

start_nonqwen() {  # name
  local stamp; stamp="$(date +%Y%m%d_%H%M%S)"; local name="$1"
  case "$name" in
    gemma4_12)
      launch gemma4_12 "2,3" 8102 "$LOGDIR/gemma4_12_$stamp.log" \
        --model google/gemma-4-12B-it --served-model-name gemma4_12 --host 127.0.0.1 --port 8102 \
        --tensor-parallel-size 2 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching --limit-mm-per-prompt '{"image":0,"audio":0}' ;;
    gemma4_26a4)
      launch gemma4_26a4 "2,3" 8102 "$LOGDIR/gemma4_26a4_$stamp.log" \
        --model cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit --served-model-name gemma4_26a4 --host 127.0.0.1 --port 8102 \
        --tensor-parallel-size 2 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching --limit-mm-per-prompt '{"image":0,"audio":0}' ;;
    ministral3_14)
      launch ministral3_14 "2,3" 8102 "$LOGDIR/ministral3_14_$stamp.log" \
        --model mistralai/Ministral-3-14B-Instruct-2512 --served-model-name ministral3_14 --host 127.0.0.1 --port 8102 \
        --tensor-parallel-size 2 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
        --enable-chunked-prefill --no-enable-prefix-caching --limit-mm-per-prompt '{"image":0}' ;;
    *) say "unknown non-Qwen model $name"; return 2 ;;
  esac
  wait_up 8102 "$name" "$(ls -t "$LOGDIR"/"$name"_*.log | head -1)"
}

stop_nonqwen() {  # name
  stop_one "$1" 8102; wait_gpu_free 2 3
}

start_qwen3_8() {
  local stamp; stamp="$(date +%Y%m%d_%H%M%S)"
  launch qwen3_8 "0" 8100 "$LOGDIR/qwen3_8_$stamp.log" \
    --model Qwen/Qwen3-8B --served-model-name qwen3_8 --host 127.0.0.1 --port 8100 \
    --tensor-parallel-size 1 --gpu-memory-utilization 0.90 --max-model-len 32768 --max-num-seqs 2 \
    --enable-chunked-prefill --no-enable-prefix-caching --trust-remote-code --reasoning-parser qwen3
  wait_up 8100 qwen3_8 "$LOGDIR/qwen3_8_$stamp.log"
}

stop_large() { stop_one qwen38_27 8097; stop_one qwen36_27 8098; wait_gpu_free 0 1 2 3; }
stop_small() { stop_one qwen3_8 8100; stop_one llama31_8 8101; wait_gpu_free 0 1; }

status() {
  for p in 8097 8098 8100 8101 8102; do echo ":$p $(served "$p") pid=$(listener_pid "$p")"; done
  nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader
}

case "${1:-status}" in
  status) status ;;
  stop-large) stop_large ;;
  start-large) start_large ;;
  stop-small) stop_small ;;
  start-small) start_small ;;
  to-small) stop_large; start_small ;;
  to-large) stop_small; start_large ;;
  start-nonqwen) start_nonqwen "${2:?model}" ;;
  stop-nonqwen) stop_nonqwen "${2:?model}" ;;
  start-qwen3_8) start_qwen3_8 ;;
  stop-qwen3_8) stop_one qwen3_8 8100; wait_gpu_free 0 ;;
  to-small2b) stop_large; start_qwen3_8; start_nonqwen "${2:?model}" ;;
  to-large2b) stop_one qwen3_8 8100; stop_one "${2:?model}" 8102; stop_one llama31_8 8101; wait_gpu_free 0 1 2 3; start_large ;;
  *) echo "unknown command $1"; exit 2 ;;
esac
