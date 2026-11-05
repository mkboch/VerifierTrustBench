"""Model configurations for Experiment 2B (development candidates and primary set)."""
QWEN_KW = {"enable_thinking": False}

MODELS = {
    "qwen38_27": {"served_name": "qwen38_27", "root": "cyankiwi/Qwen3.8-27B-AWQ-INT4", "endpoint": "http://127.0.0.1:8097",
                  "family": "qwen", "phase": "large", "gpus": "0,1", "chat_template_kwargs": QWEN_KW},
    "qwen36_27": {"served_name": "qwen36_27", "root": "QuantTrio/Qwen3.6-27B-AWQ", "endpoint": "http://127.0.0.1:8098",
                  "family": "qwen", "phase": "large", "gpus": "2,3", "chat_template_kwargs": QWEN_KW},
    "qwen3_8": {"served_name": "qwen3_8", "root": "Qwen/Qwen3-8B", "endpoint": "http://127.0.0.1:8100",
                "family": "qwen", "phase": "small", "gpus": "0", "chat_template_kwargs": QWEN_KW},
    # non-Qwen development candidates, one at a time on GPUs 2,3 port 8102
    "gemma4_12": {"served_name": "gemma4_12", "root": "google/gemma-4-12B-it", "endpoint": "http://127.0.0.1:8102",
                  "family": "gemma", "phase": "small", "gpus": "2,3", "chat_template_kwargs": {"enable_thinking": False},
                  "quantization": "none (bf16)"},
    "gemma4_26a4": {"served_name": "gemma4_26a4", "root": "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit",
                    "endpoint": "http://127.0.0.1:8102", "family": "gemma", "phase": "small", "gpus": "2,3",
                    "chat_template_kwargs": {"enable_thinking": False}, "quantization": "AWQ 4-bit (compressed-tensors)"},
    "ministral3_14": {"served_name": "ministral3_14", "root": "mistralai/Ministral-3-14B-Instruct-2512",
                      "endpoint": "http://127.0.0.1:8102", "family": "mistral", "phase": "small", "gpus": "2,3",
                      "chat_template_kwargs": None, "quantization": "FP8 weights (Marlin W8A16 on Ampere)"},
}
CANDIDATES = ["gemma4_12", "gemma4_26a4", "ministral3_14"]

# Frozen by exp2b/MODEL_BAKEOFF.md (None until the development bakeoff is complete).
SELECTED_NONQWEN = "gemma4_12"
