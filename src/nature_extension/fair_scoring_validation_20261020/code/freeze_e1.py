#!/usr/bin/env python3
"""Freeze the E1 fair-scoring protocol BEFORE the first request.

POST_HOC_FAIR_SCORING_VALIDATION. Not preregistered.

Records exactly which E1 cells are newly run and which are reused from frozen records,
with the justification for each reuse decision, and the hashes of every generator it
depends on. run_e1_openweight.py and run_e1_frontier.py both refuse to start if this
manifest has changed.
"""
from __future__ import annotations
import hashlib, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
RR = ROOT / "nature_extension/reviewer_response_20261016"
TV = ROOT / "nature_extension/final_topvenue_validation_20261018"
sys.path.insert(0, str(RR / "code"))
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
import design_heldout as D  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main() -> int:
    lad = json.loads((RR / "ladder/LADDER_DESIGN_MANIFEST.json").read_text())
    fro = json.loads((TV / "frontier/FRONTIER_LADDER_MANIFEST.json").read_text())
    subset = lad["case_ids"]
    assert subset == fro["inherits_from"]["case_ids"], "ladder and frontier subsets diverged"

    plan = D.Plan()
    cases = {c["case_id"]: c for c in plan.cases}
    papers = sorted({cases[c]["paper"] for c in subset})

    man = {
        "label": "POST_HOC_FAIR_SCORING_VALIDATION",
        "version": "E1_FAIR_SCORING-v1.0",
        "status": "POST_HOC, MOTIVATED BY INTERNAL TOP-VENUE REVIEW",
        "not_preregistered": True,
        "preregistration_note": (
            "Designed on 2026-10-20 after an internal review argued that the open-ended "
            "finding-list rungs and the binary verdict rung are not scored on comparable "
            "terms. It is post hoc and must never be described as preregistered."),
        "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "scientific_question": (
            "Does the apparent advantage of the relation-localized binary verdict rung over the "
            "relation-targeted finding-list rung survive a scoring comparison that charges both "
            "rungs for false alarms on the unmodified manuscript, and that requires the binary "
            "rung to point at the tested relation?"),
        "n_relations": len(subset),
        "case_ids": subset,
        "papers": papers,
        "n_papers": len(papers),
        "openweight_models": lad["models"],
        "frontier_model": {
            "provider": "openai",
            "model_id": fro["models"]["openai"]["model_id"],
            "reasoning": "off (reasoning_effort=none), identical to the frozen E0 frontier ladder",
        },
        "anthropic": (
            "EXCLUDED from this phase by instruction: the finding-list interface was not "
            "measurable under the frozen prompt. No new Anthropic request is issued."),
        "rungs": ["BLIND_FINDING_LIST", "CATEGORY_TARGETED_FINDING_LIST",
                  "RELATION_TARGETED_FINDING_LIST", "RELATION_LOCALIZED_BINARY_VERDICT"],
        "e1_cell_plan": {
            "openweight": {
                "BLIND_FINDING_LIST": {
                    "action": "REUSE_FROZEN",
                    "source": "runs/exp3heldout_20260918_014959/blind_trials.jsonl state=E1",
                    "granularity": "one record per (model, paper); the blind request carries no "
                                   "relation information, so all relations of a paper share it",
                    "justification": "identical relation-independent context, prompt, system, "
                                     "schema and decoding configuration; the E1 manuscript is the "
                                     "shared unmodified paper exp3heldout/papers/<paper>/E1.tex",
                    "n_records": len(lad["models"]) * len(papers),
                },
                "CATEGORY_TARGETED_FINDING_LIST": {
                    "action": "RUN_NEW",
                    "n_requests": len(lad["models"]) * len(subset),
                    "justification": "no frozen E1 record exists for this arm",
                },
                "RELATION_TARGETED_FINDING_LIST": {
                    "action": "RUN_NEW",
                    "n_requests": len(lad["models"]) * len(subset),
                    "justification": "no frozen E1 record exists for this arm",
                },
                "RELATION_LOCALIZED_BINARY_VERDICT": {
                    "action": "REUSE_FROZEN",
                    "source": "runs/exp3heldout_20260918_014959/evidence_trials.jsonl "
                              "state=E1 arm=neutral",
                    "justification": "same relation, same E1 context, same question, same neutral "
                                     "exposure, same system prompt, same schema, same decoding "
                                     "configuration and same seed derivation as the E0 binary rung",
                    "n_records": len(lad["models"]) * len(subset),
                },
            },
            "frontier_openai": {
                "BLIND_FINDING_LIST": {
                    "action": "RUN_NEW_DEDUPLICATED",
                    "n_requests": len(papers),
                    "justification": "the blind request is relation-independent and the E1 "
                                     "manuscript is shared, so the 60 relations collapse to "
                                     f"{len(papers)} distinct requests; the frozen frontier runner "
                                     "does not transmit the seed to the provider, so the "
                                     "deduplicated request is byte-identical across the relations "
                                     "of a paper. Mirrors the frozen open-weight blind E1 "
                                     "granularity.",
                },
                "CATEGORY_TARGETED_FINDING_LIST": {"action": "RUN_NEW", "n_requests": len(subset)},
                "RELATION_TARGETED_FINDING_LIST": {"action": "RUN_NEW", "n_requests": len(subset)},
                "RELATION_LOCALIZED_BINARY_VERDICT": {"action": "RUN_NEW", "n_requests": len(subset)},
            },
        },
        "held_constant_from_e0": [
            "system prompt (exp2b.protocol.SYSTEM_BLIND / the frozen targeted system prompt)",
            "response schema (exp2br.protocol_br.BLIND_SCHEMA_BR, findings maxItems 5)",
            "max_tokens 4096 finding-list / 2048 binary",
            "temperature 0 (open weight); provider default (frontier, as in the frozen E0 run)",
            "per-case seed derivation exp2b.protocol.seed_for(case_id, state)",
            "inserted-sentence generators ladder_protocol.build_arm, unchanged",
            "scorers exp2b.scoring.label_defective / label_clean / provenance, unchanged",
        ],
        "only_difference_from_e0": (
            "the manuscript variant is E1, the unmodified published text, instead of the "
            "perturbed E0 variant. No prompt wording, setting or scorer is changed."),
        "scoring": {
            "E0_sensitivity_findinglist": "exp2b.scoring.label_defective == TRUE_DETECTION",
            "E0_sensitivity_binary": "verdict == ISSUE_PRESENT",
            "E1_falsealarm_findinglist": "exp2b.scoring.label_clean == FALSE_POSITIVE; "
                                         "TARGET_TOUCHED and NO_FLAG are not false alarms, and an "
                                         "off-target finding is explicitly not a false alarm for "
                                         "the tested relation",
            "E1_falsealarm_binary": "verdict == ISSUE_PRESENT on the clean relation",
            "provenance_gate": "exp2b.scoring.provenance(...)['target_support'] in "
                               "{SUPPORTED, SUPPORTED_ADJACENT}",
            "dprime_correction": "log-linear (Hautus 1995): add 0.5 to hit and false-alarm counts "
                                 "and 1.0 to each total before converting to rates",
            "uncertainty": "manuscript-cluster bootstrap, 10,000 draws, seed 20261016",
        },
        "no_outcome_dependent_choices": (
            "Arms, scorers, gates, contrasts and the four decision labels are fixed by this "
            "manifest before the first E1 request is issued. Prompts are not tuned after seeing "
            "outputs."),
        "source_code_sha256": {
            "ladder_protocol.py": sha(RR / "code/ladder_protocol.py"),
            "run_frontier_ladder.py": sha(TV / "code/run_frontier_ladder.py"),
            "exp2b/protocol.py": sha(ROOT / "exp2b/protocol.py"),
            "exp2br/protocol_br.py": sha(ROOT / "exp2br/protocol_br.py"),
            "exp2b/scoring.py": sha(ROOT / "exp2b/scoring.py"),
            "exp3heldout/design_heldout.py": sha(ROOT / "exp3heldout/design_heldout.py"),
            "exp3heldout/ledger.json": sha(ROOT / "exp3heldout/ledger.json"),
        },
        "inherits_manifest_sha256": {
            "ladder": sha(RR / "ladder/LADDER_DESIGN_MANIFEST.json"),
            "frontier": sha(TV / "frontier/FRONTIER_LADDER_MANIFEST.json"),
        },
        "cost_controls": {
            "hard_cap_per_provider_usd": 14.0,
            "note": "Measured spend is tracked after every response and the run aborts at the cap.",
        },
    }
    # E1 manuscript hashes, so the stimulus set is pinned before the first request
    man["e1_manuscript_sha256"] = {
        p: hashlib.sha256(plan.clean_text(p)[0].encode()).hexdigest() for p in papers}

    dst = OUT / "e1/E1_FAIR_SCORING_MANIFEST.json"
    dst.write_text(json.dumps(man, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {dst}")
    print(f"manifest sha256 {sha(dst)}")
    print(f"{len(subset)} relations over {len(papers)} papers; "
          f"new open-weight requests {2 * len(lad['models']) * len(subset)}; "
          f"new frontier requests {len(papers) + 3 * len(subset)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
