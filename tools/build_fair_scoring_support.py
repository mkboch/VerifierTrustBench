#!/usr/bin/env python3
"""Derive docs/data/fair_scoring_support.json from the frozen analysis artifacts.

Two blocks that the per-cell table cannot carry, because neither is a per-cell quantity:

  scorer_audit     the human scorer-validity audit of relation-targeted misses, and the
                   four sensitivity scenarios built on it. Six colleagues rated 30 sampled
                   items; only the resulting RATES and the scenario outputs are published.
                   No per-reviewer judgment, no item text, no reviewer identifier.

  proprietary      the Anthropic arm's refusal and parser accounting. Counts only.

Both are STATIC AUDITED AGGREGATES: their confidence intervals were produced by the frozen
analysis and cannot be regenerated from the counts published here. The playground labels
them as such and does not present them as recomputed.
"""
from __future__ import annotations
import hashlib, json, os, sys
from pathlib import Path

ROOT = Path(os.environ.get("VTB_ROOT", "")).resolve()
if not (ROOT / "nature_extension").is_dir():
    sys.exit("set VTB_ROOT to the private research tree root")
D = ROOT / "nature_extension/fair_scoring_validation_20261020/data"
OUT = Path(__file__).resolve().parents[1] / "docs/data/fair_scoring_support.json"

ss = json.loads((D / "SCORER_SENSITIVITY.json").read_text())
an = json.loads((D / "ANTHROPIC_ACCOUNTING.json").read_text())
rt = json.loads((D / "RT_AUDIT_RESULTS.json").read_text())

SCENARIO_KIND = {
    "one_sided_strict": ("audit-grounded bound",
                         "Every majority-Yes human judgment is credited as a scorer false "
                         "negative on E0, with NO offsetting correction on E1. This is the "
                         "reading most generous to the criticism of the scorer."),
    "one_sided_with_partial": ("audit-grounded bound",
                               "Majority-Yes AND majority-Partially credited on E0 only. "
                               "The outer bound of the criticism."),
    "symmetric_strict": ("modelled correction",
                         "The measured rate is APPLIED to E1 near misses as well as E0 "
                         "detections. The E1 side was never audited by a human, so this "
                         "side of the correction is modelled, not measured."),
    "symmetric_with_partial": ("modelled correction",
                               "Yes plus Partially applied to both states. The E1 side is "
                               "modelled, not measured."),
}

doc = {
    "schema_version": 1,
    "what_this_is":
        "Audited aggregate results that support the fair-scoring analysis but are not "
        "per-cell quantities. Unlike fair_scoring_cells.json, the intervals here were "
        "computed by the frozen analysis and are reproduced verbatim; a visitor cannot "
        "regenerate them from the counts on this page.",
    "scorer_audit": {
        "design":
            "30 relation-targeted E0 cells the frozen scorer marked as misses were sampled "
            "under a stratified, non-proportional design across three strata and rated "
            "independently by six colleagues. A stratum's measured rate is reweighted back "
            "to the stratum's share of the corpus before it is reported.",
        "strata": {
            "A_NO_FINDINGS": "the system returned no finding at all",
            "B_OFF_TARGET": "the system returned findings, none about the tested relation",
            "C_NEAR_MISS": "the system returned a finding arguably about the tested relation",
        },
        "measured_false_negative_rate_per_stratum_pct": {
            k: round(100 * v, 2) for k, v in ss["measured_per_stratum_fn_rate"].items()},
        "measured_false_negative_rate_per_stratum_with_partial_pct": {
            k: round(100 * v, 2)
            for k, v in ss["measured_per_stratum_fn_rate_with_partial"].items()},
        "headline_false_negative_rate": {
            "raw_unweighted_pct": ss["measured_false_negative_rate"]["raw_unweighted_pct"],
            "stratum_reweighted_pct":
                ss["measured_false_negative_rate"]["stratum_reweighted_pct"],
            "ci95_pct": ss["measured_false_negative_rate"]["ci95_pct"],
            "interval_is": "static audited aggregate, not recomputed in your browser",
        },
        "counts": {
            "n_reviewers": rt["n_reviewers"],
            "n_items_sampled": rt["n_items"],
            "n_judgments": rt["judgment_level"]["total_judgments"],
            "llm_judge_used": rt["llm_judge_used"],
            "judgment_level_counts": rt["judgment_level"]["counts"],
            "item_level_majority_counts": rt["item_level"]["majority_counts"],
            "unanimous_items": rt["item_level"]["unanimous_items"],
            "items_with_any_yes_or_partial": rt["item_level"]["items_with_any_yes_or_partial"],
            "note":
                "Two units, both correct and not interchangeable: an ITEM is one sampled "
                "miss resolved by majority across six reviewers; a JUDGMENT is one "
                "reviewer's answer on one item. Rates quoted per item and per judgment "
                "differ for that reason, not because they disagree.",
        },
        "agreement": {
            "fleiss_kappa_4level": rt["agreement"]["fleiss_kappa_4level"],
            "fleiss_kappa_binary": rt["agreement"]["fleiss_kappa_binary_credited_vs_not"],
            "mean_pairwise_raw_agreement_4level":
                rt["agreement"]["mean_pairwise_raw_agreement_4level"],
            "mean_pairwise_raw_agreement_binary":
                rt["agreement"]["mean_pairwise_raw_agreement_binary"],
            "prevalence_caveat":
                "Most items are true scorer misses, so agreement is measured against a "
                "skewed base rate; kappa is reported with raw agreement rather than "
                "instead of it. Per-reviewer and per-pair figures are NOT published: six "
                "identifiable colleagues produced them.",
        },
        "e1_near_misses_were_not_audited":
            "The audit sampled E0 misses only. The 61 E1 near misses received NO human "
            "rating. Any scenario that corrects the E1 side applies the E0-measured rate "
            "to unaudited cells, which is a modelling assumption and is labelled as one.",
        "frozen_primary": ss["frozen_primary"],
        "n_paired_cells": ss["n_paired_cells"],
        "n_manuscripts": ss["n_manuscripts"],
        "scenarios": [
            dict(id=k, kind=SCENARIO_KIND[k][0], basis=SCENARIO_KIND[k][1], **v)
            for k, v in ss["scenarios"].items()
        ],
        "verdict": ss["verdict"],
    },
    "proprietary_replication": {
        "anthropic": {
            "model": an["model"],
            "scope": an["scope"],
            "binary_verdict_rung": an["binary_verdict_rung"],
            "accuracy": an["accuracy"],
            "finding_list_rungs_conclusion": an["finding_list_rungs"]["conclusion"],
            "refusals_are_not_failures":
                "A policy refusal is the provider declining to produce a response. It is "
                "an interface and availability fact, not evidence about verification "
                "ability, and it is reported separately rather than scored as an error.",
            "parser_note":
                "The strict frozen parser accepts only a correctly fenced JSON object. "
                "A looser parser that scans for the outermost braces recovers 6 further "
                "records; both readings are reported, and the scoring rule is identical "
                "in each. The parser is not tuned after seeing the results.",
        },
    },
}

OUT.parent.mkdir(parents=True, exist_ok=True)
text = json.dumps(doc, separators=(",", ":")) + "\n"
OUT.write_text(text)
print(f"wrote {OUT.name}  {len(text)} bytes  sha256 {hashlib.sha256(text.encode()).hexdigest()}")
