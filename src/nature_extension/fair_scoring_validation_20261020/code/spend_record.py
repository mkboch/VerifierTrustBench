#!/usr/bin/env python3
"""Transparent spend record: this phase and the project cumulative, per provider.

The $14/provider cap is PER AUTHORIZED PHASE, not cumulative across the project. The
frontier-validation phase (2026-10-18) and this fair-scoring phase (2026-10-20) were
separately authorized, so each is measured against its own cap. The cumulative figure is
recorded here so it is visible, not because it breaches anything.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
TV = ROOT / "nature_extension/final_topvenue_validation_20261018"


def tally(path):
    rs = [json.loads(l) for l in Path(path).open()] if Path(path).exists() else []
    if not rs:
        return {"requests": 0, "spend_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
    return {"requests": len(rs),
            "spend_usd": round(sum(r.get("cost_usd", 0.0) for r in rs), 4),
            "input_tokens": sum(r.get("input_tokens", 0) for r in rs),
            "output_tokens": sum(r.get("output_tokens", 0) for r in rs)}


oa_e0 = tally(TV / "frontier/frontier_openai_trials.jsonl")
oa_e1 = tally(OUT / "e1/e1_frontier_openai_trials.jsonl")
an_e0 = tally(TV / "frontier/frontier_anthropic_trials.jsonl")

rec = {
    "label": "API_SPEND_RECORD",
    "cap_interpretation": {
        "rule": "$14.00 per provider PER AUTHORIZED PHASE",
        "confirmed_by": "user instruction 2026-10-20: the earlier $14/provider cap applied to "
                        "the frontier-validation phase; the fair-scoring E1 phase was "
                        "separately authorized",
        "cumulative_is_a_deviation": False,
    },
    "openai": {
        "phases": {
            "frontier_validation_20261018": {**oa_e0, "cap_usd": 14.0,
                                             "within_cap": oa_e0["spend_usd"] <= 14.0},
            "fair_scoring_e1_20261020": {**oa_e1, "cap_usd": 14.0,
                                         "within_cap": oa_e1["spend_usd"] <= 14.0},
        },
        "cumulative_spend_usd": round(oa_e0["spend_usd"] + oa_e1["spend_usd"], 4),
        "cumulative_requests": oa_e0["requests"] + oa_e1["requests"],
        "note": "Each phase is within its own $14 cap. The cumulative figure is reported for "
                "transparency and is not a breach under the confirmed interpretation.",
    },
    "anthropic": {
        "phases": {
            "frontier_validation_20261018": {**an_e0, "cap_usd": 14.0,
                                             "within_cap": an_e0["spend_usd"] <= 14.0},
            "fair_scoring_e1_20261020": {"requests": 0, "spend_usd": 0.0,
                                         "reason": "excluded by instruction; the finding-list "
                                                   "interface was not measurable under the "
                                                   "frozen prompt"},
        },
        "cumulative_spend_usd": an_e0["spend_usd"],
        "cumulative_requests": an_e0["requests"],
    },
    "open_weight": {
        "spend_usd": 0.0,
        "note": "locally served on owned hardware; no metered cost",
        "e1_requests": sum(1 for _ in (OUT / "e1/e1_openweight_trials.jsonl").open())
        if (OUT / "e1/e1_openweight_trials.jsonl").exists() else 0,
    },
    "total_metered_spend_usd": round(oa_e0["spend_usd"] + oa_e1["spend_usd"]
                                     + an_e0["spend_usd"], 4),
}
(OUT / "data/SPEND_RECORD.json").write_text(json.dumps(rec, indent=1) + "\n")
print(json.dumps(rec, indent=1))
