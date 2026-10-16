#!/usr/bin/env python3
"""Context-length gate (actual tokenizer counts). For every 2B manuscript (E1) and every primary model, counts the
chat-templated blind request and the longest targeted request (false_rationale exposure, longest question) and
requires prompt_tokens + max_tokens + 256 <= max_model_len (32,768 for every primary model in 2B).

    python exp2b/context_gate.py --papers 2609.03933 ... --models qwen38_27 qwen36_27 qwen3_8 <nonqwen>
Writes exp2b/CONTEXT_GATE.json and prints a table; exits 1 if any paper fails for any model."""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2b")); sys.path.insert(0, str(ROOT / "exp2b/cases"))
import importlib
import models as M, normalize as N, protocol as P
from transformers import AutoTokenizer

MAX_MODEL_LEN = 32768
MARGIN = 256
ap = argparse.ArgumentParser(); ap.add_argument("--papers", nargs="+"); ap.add_argument("--models", nargs="+"); ap.add_argument("--blind-prompt", default=None)
a = ap.parse_args()
pid = a.blind_prompt or P.BLIND_PROMPT_ID or "B2_dimensions"
res, fail = {}, False
for m in a.models:
    cfg = M.MODELS[m]
    tok = AutoTokenizer.from_pretrained(cfg["root"], **({"fix_mistral_regex": True} if "mistral" in cfg["root"].lower() else {}))
    kw = cfg.get("chat_template_kwargs") or {}
    for p in a.papers:
        text, _ = N.number((ROOT / f"exp2b/papers/{p}/E1.tex").read_text())
        mod = importlib.import_module("p" + p.replace(".", "_"))
        q = max((c["question"] for c in mod.CASES), key=len)
        rat = max((r[s]["false"] for r in mod.RATIONALES.values() for s in ("E0", "E1")), key=len)
        blind = P.build_blind(cfg, text, 1, prompt_id=pid)[0]["messages"]
        targ = P.build_targeted(cfg, text, q, P.exposure_text("false_rationale", prior_verdict="ISSUE_PRESENT", prior_rationale=rat), 1)[0]["messages"]
        counts = {}
        for name, msgs, kind in (("blind", blind, "blind"), ("targeted_longest", targ, "targeted")):
            ids = tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, **kw)
            ids = ids["input_ids"] if hasattr(ids, "keys") else ids
            n = len(ids[0] if ids and isinstance(ids[0], list) else ids)
            counts[name] = {"prompt_tokens": n, "max_tokens": P.MAX_TOKENS[kind], "total": n + P.MAX_TOKENS[kind] + MARGIN,
                            "fits": n + P.MAX_TOKENS[kind] + MARGIN <= MAX_MODEL_LEN}
            fail |= not counts[name]["fits"]
        res[f"{m}|{p}"] = counts
        print(f"{m:14s} {p} blind={counts['blind']['prompt_tokens']:6d} targeted={counts['targeted_longest']['prompt_tokens']:6d} "
              f"fits={counts['blind']['fits'] and counts['targeted_longest']['fits']}", flush=True)
(ROOT / "exp2b/CONTEXT_GATE.json").write_text(json.dumps({"blind_prompt": pid, "max_model_len": MAX_MODEL_LEN, "margin": MARGIN, "results": res}, indent=1))
sys.exit(1 if fail else 0)
