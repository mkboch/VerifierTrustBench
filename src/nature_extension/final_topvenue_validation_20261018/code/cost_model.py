#!/usr/bin/env python3
"""2B: cost model and largest-affordable-N calculation for the frontier ladder.

Token counts are exact (measured). PRICES ARE NOT VERIFIABLE FROM THIS MACHINE: no credential is
configured, so no pricing or billing endpoint can be queried. The table below is therefore
evaluated across a range of price points. Before any spend, the actual price for the chosen model
must be read from the provider's pricing page and substituted.
"""
from __future__ import annotations
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
TK = json.loads((OUT / "data/FRONTIER_TOKEN_COUNTS.json").read_text())

N_REL = TK["n_relations"]
IN_PER_REL = TK["total_input_tokens_per_model"] / N_REL          # across all 4 rungs
REQ_PER_REL = TK["n_requests_per_model"] / N_REL                 # = 4
CAP = 14.00

# Realistic output: the completed open-weight ladder averaged ~1.5 findings/case on blind and
# ~0.6 on targeted; a finding is ~60 tokens, plus audit_notes. 600 output tokens per finding-list
# response and 250 per verdict response is generous. Reasoning models additionally bill hidden
# reasoning tokens, modelled separately.
OUT_PER_REL_BASE = 3 * 600 + 250
REASONING_MULTIPLIERS = {"none/low": 0, "medium": 1500 * 4, "high": 4000 * 4}

PRICE_POINTS = [
    ("budget reasoning tier", 1.25, 10.00),
    ("mid tier", 3.00, 15.00),
    ("high tier", 5.00, 25.00),
    ("flagship tier", 15.00, 75.00),
]

print("Exact measured volume for ONE model, full 60-relation four-rung ladder:")
print(f"  requests      {TK['n_requests_per_model']}")
print(f"  input tokens  {TK['total_input_tokens_per_model']:,}  "
      f"({IN_PER_REL:,.0f} per relation across all four rungs)")
print(f"  mean prompt   {TK['per_rung']['BLIND_FINDING_LIST']['mean_input_tokens']:,} tokens "
      f"(a full manuscript)")
print()

rows = []
print(f"{'price tier':24}{'$/M in':>8}{'$/M out':>9}{'reasoning':>12}"
      f"{'full-60 cost':>14}{'max N <= $14':>14}{'batch max N':>13}")
print("-" * 94)
for name, pin, pout in PRICE_POINTS:
    for rlabel, rtok in REASONING_MULTIPLIERS.items():
        out_per_rel = OUT_PER_REL_BASE + rtok
        cost_per_rel = (IN_PER_REL / 1e6) * pin + (out_per_rel / 1e6) * pout
        full = cost_per_rel * N_REL
        max_n = int(CAP // cost_per_rel)
        max_n_batch = int(CAP // (cost_per_rel * 0.5))      # 50% batch discount
        rows.append({"tier": name, "price_in_per_m": pin, "price_out_per_m": pout,
                     "reasoning": rlabel, "cost_per_relation": round(cost_per_rel, 4),
                     "full_60_cost": round(full, 2),
                     "max_relations_under_cap": min(max_n, N_REL),
                     "max_relations_under_cap_with_batch": min(max_n_batch, N_REL)})
        print(f"{name:24}{pin:>8.2f}{pout:>9.2f}{rlabel:>12}"
              f"{full:>13.2f} {min(max_n,N_REL):>13}{min(max_n_batch,N_REL):>13}")

print(f"\nHard cap per provider: ${CAP:.2f}. 'max N' is the largest number of relations whose")
print("full four-rung ladder fits under the cap at that price and reasoning setting.")

feasible_full = [r for r in rows if r["full_60_cost"] <= CAP]
feasible_batch = [r for r in rows if r["full_60_cost"] * 0.5 <= CAP]
print(f"\nprice/reasoning combinations where the FULL 60-relation ladder fits under ${CAP:.2f}:")
print(f"  without batch discount: {len(feasible_full)} of {len(rows)}")
for r in feasible_full:
    print(f"    {r['tier']} @ reasoning {r['reasoning']}: ${r['full_60_cost']:.2f}")
print(f"  with a 50% batch discount: {len(feasible_batch)} of {len(rows)}")
for r in feasible_batch:
    print(f"    {r['tier']} @ reasoning {r['reasoning']}: ${r['full_60_cost']*0.5:.2f}")

json.dump({"hard_cap_per_provider_usd": CAP,
           "token_counts_are_measured": True,
           "prices_are_assumed_not_verified": True,
           "verification_required_before_spend": (
               "No credential is configured on this machine, so neither a models endpoint nor a "
               "billing endpoint could be queried. Every dollar figure here is the measured token "
               "count multiplied by an ASSUMED price. Substitute the provider's current published "
               "price for the chosen model before issuing any request."),
           "input_tokens_per_relation_all_rungs": round(IN_PER_REL),
           "assumed_output_tokens_per_relation_base": OUT_PER_REL_BASE,
           "reasoning_token_assumptions": REASONING_MULTIPLIERS,
           "scenarios": rows},
          (OUT / "data/FRONTIER_COST_PREFLIGHT.json").open("w"), indent=1)
print("\nwrote data/FRONTIER_COST_PREFLIGHT.json")
