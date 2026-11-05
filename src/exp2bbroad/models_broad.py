"""Experiment 2B-broad model registry.

Twelve models from ten independently developed families. Four (the 2B primaries) are NOT rerun: their records come from the
immutable runs `runs/exp2b_20260914_142911` (evidence, matrix) and `runs/exp2br_20260914_214259` (blind). Eight candidates are
run here with the identical frozen protocol.

`reasoning_mode` is frozen before inference:
  direct            - the model answers in one structured response; where a vendor documents a thinking switch it is set to off
                      (Granite `enable_thinking: False`, EXAONE `enable_thinking: False`, Seed-OSS `thinking_budget: 0`,
                      Qwen/Gemma `enable_thinking: False`), which is the documented non-reasoning mode of that model.
  native_reasoning  - the model always reasons before answering; hidden reasoning is separated by the server's reasoning parser
                      and never scored. Only gpt-oss-20b is in this regime (lowest documented effort, "low").

`competence_class` records the outcome of the FROZEN eligibility bakeoff of Experiment 2B-family and is never recomputed here:
  primary           - passed the frozen competence gate (Qwen, Gemma models of 2B)
  characterization  - technically viable but did not pass that gate (every candidate added in this experiment)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("exp2b", "exp2bfamily"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))
import models as M2B  # noqa: E402  (exp2b/models.py, frozen)

CANDIDATE_PORT = "http://127.0.0.1:8104"

# ---------------------------------------------------------------- new candidates (run in this experiment)
CANDIDATES = {
    "mistral_small32": {
        "served_name": "mistral_small32", "root": "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
        "revision": "95a6d26c4bfb886c58daf9d3f7332c857cb27b43", "family": "Mistral", "params_b": 24,
        "quantization": "none (bf16)", "reasoning_mode": "direct", "chat_template_kwargs": None,
        "endpoint": CANDIDATE_PORT, "gpus": "0,1,2,3", "tp": 4},
    "olmo31_32": {
        "served_name": "olmo31_32", "root": "allenai/Olmo-3.1-32B-Instruct",
        "revision": "ac0587e4a7744a551c059d8cd17ba220bc940dae", "family": "OLMo", "params_b": 32,
        "quantization": "none (bf16)", "reasoning_mode": "direct", "chat_template_kwargs": None,
        "endpoint": CANDIDATE_PORT, "gpus": "0,1,2,3", "tp": 4},
    "llama33_70awq": {
        "served_name": "llama33_70awq", "root": "casperhansen/llama-3.3-70b-instruct-awq",
        "revision": "64d255621f40b42adaf6d1f32a47e1d4534c0f14", "family": "Llama", "params_b": 70,
        "quantization": "AWQ INT4 g128 (awq_marlin)", "reasoning_mode": "direct", "chat_template_kwargs": None,
        "endpoint": CANDIDATE_PORT, "gpus": "0,1,2,3", "tp": 4},
    "gptoss_20": {
        "served_name": "gptoss_20", "root": "openai/gpt-oss-20b", "revision": "6cee5e81ee83917806bbde320786a8fb61efebee",
        "family": "gpt-oss", "params_b": 21, "params_note": "MoE, 3.6B active", "quantization": "native MXFP4",
        "reasoning_mode": "native_reasoning", "reasoning_effort": "low", "chat_template_kwargs": None,
        "extra_payload": {"reasoning_effort": "low"}, "endpoint": CANDIDATE_PORT, "gpus": "0", "tp": 1},
    "glm4_32": {
        "served_name": "glm4_32", "root": "zai-org/GLM-4-32B-0414", "revision": "077b5c2f5c43bd3239fd605a0600229e8facbd4a",
        "family": "GLM", "params_b": 32, "quantization": "none (bf16)", "reasoning_mode": "direct",
        "chat_template_kwargs": None, "endpoint": CANDIDATE_PORT, "gpus": "0,1,2,3", "tp": 4},
    "granite42_30": {
        "served_name": "granite42_30", "root": "ibm-granite/granite-4.2-30b", "revision": "9e668ce1c538387ef24d3644e9b0606647762636",
        "family": "Granite", "params_b": 30, "quantization": "none (bf16)", "reasoning_mode": "direct",
        "chat_template_kwargs": {"enable_thinking": False}, "endpoint": CANDIDATE_PORT, "gpus": "0,1,2,3", "tp": 4},
    "exaone45_33": {
        "served_name": "exaone45_33", "root": "LGAI-EXAONE/EXAONE-4.5-33B", "revision": "570aa4b15a4f45ba1133072b45f50198f6e3b4fd",
        "family": "EXAONE", "params_b": 33, "quantization": "none (bf16)", "reasoning_mode": "direct",
        "chat_template_kwargs": {"enable_thinking": False}, "endpoint": CANDIDATE_PORT, "gpus": "0,1,2,3", "tp": 4},
    "seedoss_36": {
        "served_name": "seedoss_36", "root": "ByteDance-Seed/Seed-OSS-36B-Instruct", "revision": "497f1dca95ebdec98e41d517b9f060ee753c902f",
        "family": "Seed", "params_b": 36, "quantization": "none (bf16)", "reasoning_mode": "direct",
        "chat_template_kwargs": {"thinking_budget": 0}, "endpoint": CANDIDATE_PORT, "gpus": "0,1,2,3", "tp": 4},
}

# ---------------------------------------------------------------- 2B primaries (records reused, not rerun)
REUSED = {
    "qwen38_27": {"family": "Qwen", "params_b": 27, "quantization": "AWQ INT4", "reasoning_mode": "direct"},
    "qwen36_27": {"family": "Qwen", "params_b": 27, "quantization": "AWQ INT4", "reasoning_mode": "direct"},
    "qwen3_8": {"family": "Qwen", "params_b": 8, "quantization": "none (bf16)", "reasoning_mode": "direct"},
    "gemma4_12": {"family": "Gemma", "params_b": 12, "quantization": "none (bf16)", "reasoning_mode": "direct"},
}

MODELS = {**M2B.MODELS, **CANDIDATES}
for _m, _meta in REUSED.items():
    MODELS[_m] = {**MODELS[_m], **_meta}

COMPETENCE_CLASS = {**{m: "primary" for m in REUSED}, **{m: "characterization" for m in CANDIDATES}}
RUN_HERE = list(CANDIDATES)
ALL_MODELS = list(REUSED) + RUN_HERE

# Excluded checkpoints (technical only; recorded in FROZEN_DESIGN.md)
EXCLUDED = {
    "RedHatAI/Llama-3.3-70B-Instruct-quantized.w4a16": "constrained decoding degenerate under five flag sets (2B-family);"
    " replaced by the working AWQ build of the same base",
    "allenai/Olmo-3-32B-Think": "reasoning traces do not fit the frozen max_tokens budget (2048 targeted); using a larger budget"
    " would change the frozen generation protocol",
}


def apply_extra(cfg, built):
    """Add frozen model-specific technical request fields (gpt-oss reasoning_effort); recompute request_sha256."""
    payload, prov = built
    extra = cfg.get("extra_payload")
    if not extra:
        return payload, prov
    from client import canonical, sha256_text
    payload = {**payload, **extra}
    prov = {**prov, "extra_payload": extra, "request_sha256": sha256_text(canonical(payload))}
    return payload, prov


def family_of(m):
    return MODELS[m]["family"]
