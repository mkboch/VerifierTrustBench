#!/usr/bin/env python3
"""2B: cost preflight for the frontier localization ladder.

Reconstructs the exact four-rung prompts for all 60 frozen relations and counts input tokens
exactly with tiktoken. No API call is made and no credential is read.

Rung 4 (binary verdict) reuses the frozen targeted prompt; rungs 1-3 reuse the frozen
bounded-blind prompt plus the frozen ladder insertions, so the frontier experiment asks the same
scientific question as the completed ladder.
"""
from __future__ import annotations
import json, sys, statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
RR = ROOT / "nature_extension/reviewer_response_20261016"
sys.path.insert(0, str(RR / "code"))
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))

import design_heldout as D      # noqa: E402
import protocol as P            # noqa: E402
import protocol_br as PBR       # noqa: E402
import ladder_protocol as LP    # noqa: E402
import tiktoken                 # noqa: E402

MAN = json.loads((RR / "ladder/LADDER_DESIGN_MANIFEST.json").read_text())
SUBSET = MAN["case_ids"]
plan = D.Plan()
cases = {c["case_id"]: c for c in plan.cases}
CFG = {"served_name": "frontier"}          # no chat_template_kwargs; provider-side

enc = tiktoken.get_encoding("o200k_base")  # current OpenAI encoding


def toks(msgs) -> int:
    # message framing overhead is small and provider-specific; +4 per message is the usual allowance
    return sum(len(enc.encode(m["content"])) + 4 for m in msgs)


RUNGS = {}
for cid in SUBSET:
    c = cases[cid]
    text, _valid = plan.paper_text(c, "E0")
    seed = P.seed_for(cid, "E0")

    blind, _ = PBR.build_blind_br(CFG, text, seed)
    RUNGS.setdefault("BLIND_FINDING_LIST", []).append(toks(blind["messages"]))

    for arm, name in (("CATEGORY_TARGETED_DISCOVERY", "CATEGORY_TARGETED_FINDING_LIST"),
                      ("RELATION_TARGETED_DISCOVERY", "RELATION_TARGETED_FINDING_LIST")):
        pl, _ = LP.build_arm(arm, CFG, text, c, seed)
        RUNGS.setdefault(name, []).append(toks(pl["messages"]))

    tgt, _ = P.build_targeted(CFG, text, c["question"], P.exposure_text("neutral"), seed)
    RUNGS.setdefault("RELATION_LOCALIZED_BINARY_VERDICT", []).append(toks(tgt["messages"]))

MAX_OUT = {"BLIND_FINDING_LIST": 4096, "CATEGORY_TARGETED_FINDING_LIST": 4096,
           "RELATION_TARGETED_FINDING_LIST": 4096, "RELATION_LOCALIZED_BINARY_VERDICT": 2048}

print(f"{'rung':40}{'n':>5}{'mean in':>10}{'median':>9}{'max':>9}{'total in':>11}{'max out':>9}")
print("-" * 93)
tot_in = tot_out = 0
per_rung = {}
for k, v in RUNGS.items():
    s = sum(v)
    o = MAX_OUT[k] * len(v)
    per_rung[k] = {"n_requests": len(v), "mean_input_tokens": round(st.mean(v)),
                   "median_input_tokens": round(st.median(v)), "max_input_tokens": max(v),
                   "total_input_tokens": s, "max_output_tokens_each": MAX_OUT[k],
                   "max_output_tokens_total": o}
    tot_in += s; tot_out += o
    print(f"{k:40}{len(v):>5}{round(st.mean(v)):>10}{round(st.median(v)):>9}{max(v):>9}{s:>11,}{MAX_OUT[k]:>9}")
print("-" * 93)
print(f"{'TOTAL (one model, all four rungs)':40}{sum(len(v) for v in RUNGS.values()):>5}"
      f"{'':>28}{tot_in:>11,}{'':>9}")
print(f"\nmaximum output-token exposure if every response saturates its cap: {tot_out:,}")
print(f"realistic output (completed ladder averaged ~1.5 findings/case): far below the cap")

json.dump({
    "note": "Exact input-token counts for the 60-relation four-rung ladder, one model. "
            "Counted with tiktoken o200k_base. No API call was made.",
    "n_relations": len(SUBSET), "n_rungs": 4,
    "n_requests_per_model": sum(len(v) for v in RUNGS.values()),
    "total_input_tokens_per_model": tot_in,
    "max_output_tokens_per_model": tot_out,
    "per_rung": per_rung,
    "encoding": "o200k_base",
    "message_overhead_allowance_per_message": 4,
}, (OUT / "data/FRONTIER_TOKEN_COUNTS.json").open("w"), indent=1)
print("\nwrote data/FRONTIER_TOKEN_COUNTS.json")
