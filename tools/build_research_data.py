#!/usr/bin/env python3
"""Derive the remaining public research data from the frozen records.

Produces two files.

docs/data/research_results.json
    Aggregate outcome blocks for the parts of the study that the per-cell ladder table and
    the sufficient-statistics file do not carry: the three-state E0/E1/E2 localized task,
    the frontier replications, the four scorer-correction scenarios, the gold-label
    validation, the contamination chronology, the denominator reconciliation and the
    anatomy of the relation-targeted misses. Numerators and denominators are carried
    wherever the frozen record carries them, so rates are recomputable rather than quoted.

docs/data/manuscript_results_index.json
    The source-of-truth manifest: every manuscript macro, its frozen value, the canonical
    record it came from, and how a reader can reproduce it -- recomputable from the public
    release, a retained audited aggregate, or restricted. This is what the parity audit
    walks, and it is what makes "which results are reproducible" a checkable claim rather
    than a sentence in a README.

Nothing here is recomputed from the manuscript. Every value is read from a frozen record.
"""
from __future__ import annotations
import hashlib, json, os, re, sys
from pathlib import Path

ROOT = Path(os.environ.get("VTB_ROOT", "")).resolve()
if not (ROOT / "nature_extension").is_dir():
    sys.exit("set VTB_ROOT to the private research tree root")
PUB = Path(__file__).resolve().parents[1] / "docs/data"
FS = ROOT / "nature_extension/fair_scoring_validation_20261020/data"
TV = ROOT / "nature_extension/final_topvenue_validation_20261018/data"
RR = ROOT / "nature_extension/reviewer_response_20261016/data"
STMT_TEXT = (
    "An E0 defect is a perturbation THIS STUDY injected into a sound published "
    "manuscript. No number in this file asserts that any real paper contains an error. "
    "Manuscripts appear only as opaque labels.")
sys.path.insert(0, str(ROOT / "nature_extension/fair_scoring_validation_20261020/code"))
import fairlib as F  # noqa: E402


def cluster_map():
    """The SAME opaque manuscript labels the per-cell table uses, so the two join."""
    f = F.Fair()
    papers = sorted({c["paper"] for c in f.cells.values()})
    return {p: f"M{i + 1:02d}" for i, p in enumerate(papers)}


def pseudonymise_chronology(chron, cmap):
    """Replace arXiv identifiers with opaque cluster labels.

    The chronology's scientific job is to show that every held-out manuscript was posted
    after every evaluated model's training cutoff. That argument needs the DATES, not the
    identities, so the dates stay and the identifiers go. Residual risk is noted in
    DATA_SHARING_AND_PRIVACY_REVIEW.md: a posting date plus a domain narrows the candidate
    set, but does not identify a paper.
    """
    out = json.loads(json.dumps(chron))
    ms = out.get("manuscripts")
    if isinstance(ms, dict):
        for field, byid in list(ms.items()):
            if isinstance(byid, dict):
                ms[field] = {cmap.get(k, k): v for k, v in byid.items()}
    unmapped = [k for k in json.dumps(out).split('"')
                if re.fullmatch(r"26\d\d\.\d{4,5}", k)]
    if unmapped:
        sys.exit(f"chronology still carries identifiers: {sorted(set(unmapped))[:5]}")
    # Derived, not asserted: does each checkpoint predate every held-out manuscript?
    # Where it does not, chronology does NOT rule memorisation out, and saying so is the
    # point of carrying this block at all.
    last = out["manuscripts"]["last_posted_utc"]
    first = out["manuscripts"]["first_posted_utc"]
    verdict = {}
    for mdl, rec in (out.get("open_weight") or {}).items():
        created = ((rec.get("served") or {}).get("created_utc") or "")[:19].replace(".000", "")
        ok = bool(created) and created < last[:19]
        verdict[mdl] = {
            "served_checkpoint_created_utc": created or None,
            "predates_every_held_out_manuscript": ok,
            "memorisation_ruled_out_by_ordering": ok,
        }
    fr = out.get("frontier_gpt_5_2") or {}
    snap = (fr.get("snapshot_date") or "")[:19]
    if snap:
        verdict[fr.get("model_id", "frontier")] = {
            "served_checkpoint_created_utc": snap,
            "predates_every_held_out_manuscript": snap < last[:19],
            "memorisation_ruled_out_by_ordering": snap < last[:19],
        }
    out["ordering_verdict_by_system"] = verdict
    out["ordering_summary"] = {
        "manuscripts_first_posted_utc": first,
        "manuscripts_last_posted_utc": last,
        "n_systems_ruled_out_by_ordering":
            sum(1 for v in verdict.values() if v["memorisation_ruled_out_by_ordering"]),
        "n_systems_not_ruled_out":
            sum(1 for v in verdict.values() if not v["memorisation_ruled_out_by_ordering"]),
        "reading": ("A checkpoint published AFTER a manuscript could in principle have "
                    "seen it. Where that is the case the ordering establishes nothing and "
                    "this file says so. It is not evidence that memorisation occurred."),
    }
    out["manuscript_labels_are_opaque"] = (
        "Manuscripts appear as the same opaque cluster labels used in "
        "fair_scoring_cells.json. The label-to-arXiv mapping is not published.")
    return out


def J(p):
    return json.load(open(p))


# how each canonical record's values reach the public, and why
ROUTE = {
    "FAIR_LADDER_METRICS.json": ("recomputable",
        "recomputed from docs/data/fair_scoring_cells.json"),
    "LADDER_DECOMPOSITION.json": ("recomputable",
        "recomputed from docs/data/fair_scoring_cells.json"),
    "LADDER_RESULTS.json": ("recomputable",
        "recomputed from docs/data/fair_scoring_cells.json"),
    "CLUSTER_ROBUST_PRIMARY.json": ("recomputable",
        "recomputed from docs/data/public_sufficient_statistics.json"),
    "TRANSFER_CONTRASTS.json": ("recomputable",
        "recomputed from docs/data/public_sufficient_statistics.json"),
    "TRANSFER_RECONCILIATION.json": ("recomputable",
        "recomputed from docs/data/public_sufficient_statistics.json"),
    "RT_AUDIT_RESULTS.json": ("recomputable",
        "recomputed from docs/data/scorer_audit_items.json (per-item counts)"),
    "AUDIT_AGREEMENT.json": ("mixed",
        "item-level statistics recomputable from scorer_audit_items.json; reviewer-axis "
        "pairwise agreement is a retained audited aggregate"),
    "AUDIT_IMPACT.json": ("audited_aggregate",
        "carried in research_results.json; depends on withheld audited items"),
    "AUDIT_DISAGREEMENTS.json": ("audited_aggregate",
        "carried in research_results.json"),
    "SCORER_SENSITIVITY.json": ("audited_aggregate",
        "all four correction scenarios carried in research_results.json; they re-score "
        "withheld audited items, so they are not recomputable from public counts"),
    "ANTHROPIC_ACCOUNTING.json": ("recomputable",
        "recomputed from research_results.json frontier.anthropic counts"),
    "FRONTIER_RESULTS.json": ("recomputable",
        "recomputed from research_results.json frontier counts"),
    "FRONTIER_LADDER_MANIFEST.json": ("audited_aggregate",
        "run manifest; counts carried in research_results.json"),
    "TRAINING_CHRONOLOGY.json": ("audited_aggregate",
        "carried in research_results.json; depends on model release metadata"),
    "DENOMINATOR_RECONCILIATION.json": ("recomputable",
        "carried in research_results.json with every numerator and denominator"),
    "MISS_ANATOMY.json": ("recomputable",
        "carried in research_results.json with counts"),
    "UNITARY_VS_PROFILE_12SYSTEM.json": ("audited_aggregate",
        "twelve-system profile analysis; carried as aggregates"),
    "PROFILE_AXIS_CORRELATIONS_12SYSTEM.csv": ("audited_aggregate",
        "carried as aggregates"),
    "PROFILE_RANKING_SUMMARY_12SYSTEM.json": ("audited_aggregate",
        "carried as aggregates"),
    "LOCALIZED_BIAS_AWARE_METRICS.csv": ("audited_aggregate",
        "carried as aggregates"),
    "NATURAL_ERROR_USABLE.json": ("restricted",
        "concerns naturally occurring errors in third-party manuscripts; not published"),
    "NATURAL_ERROR_LEDGER.json": ("restricted",
        "concerns naturally occurring errors in third-party manuscripts; not published"),
    "CORRECTION_CANDIDATES_WIDE.json": ("restricted",
        "concerns naturally occurring errors in third-party manuscripts; not published"),
    "BLIND_SCORER_AUDIT_ITEMS.json": ("restricted",
        "the audited items contain manuscript text and model output; only per-item "
        "rating counts are published, in scorer_audit_items.json"),
    "final_numbers.py": ("recomputable",
        "Experiment 3 and extension counts; recomputable from "
        "docs/data/public_sufficient_statistics.json where the counts are carried"),
}


def research_results():
    fn = J(ROOT / "paper_final/FINAL_NUMBERS.json")
    sens = J(FS / "SCORER_SENSITIVITY.json")
    anth = J(FS / "ANTHROPIC_ACCOUNTING.json")
    fr = J(TV / "FRONTIER_RESULTS.json")
    den = J(FS / "DENOMINATOR_RECONCILIATION.json")
    miss = J(FS / "MISS_ANATOMY.json")
    chron = J(FS / "TRAINING_CHRONOLOGY.json")
    dec = J(RR / "LADDER_DECOMPOSITION.json")
    imp = J(TV / "AUDIT_IMPACT.json")
    cmap = cluster_map()

    def num(k):
        v = fn.get(k)
        if v is None:
            sys.exit(f"missing macro {k} in FINAL_NUMBERS.json")
        return int(str(v).replace(",", ""))

    def frac(k):
        """Parse a frozen 'x/n (p%)' macro into explicit numerator and denominator."""
        v = str(fn.get(k, ""))
        if "/" not in v:
            sys.exit(f"macro {k} is not a fraction: {v!r}")
        a, b = v.split("(")[0].strip().split("/")
        return {"x": int(a), "n": int(b)}

    return {
        "schema_version": 1,
        "what_this_is": __doc__.strip().split("\n\n")[0],
        "defects_are_synthetic": (
            "Every E0 defect is a perturbation THIS STUDY injected into a sound published "
            "manuscript. No number here asserts that any real paper contains an error."),
        "three_state_localized": {
            "label": "Relation-localized verdict in three evidence states",
            "note": ("E0 is the perturbed state, E1 the manuscript as published, E2 an "
                     "alternate perturbation. Denominators differ because validity is "
                     "judged per state."),
            "E0_defective": frac("h2_e0"),
            "E1_as_published": frac("h2_e1"),
            "E2_alternate": frac("h2_e2"),
            "correct_in_all_three": frac("h2_traj"),
            "cited_relation_but_wrong_verdict": num("p0_irs_total"),
        },
        "ladder_decomposition": dec,
        "scorer_correction_scenarios": {
            "note": ("Four scenarios, not one. They differ in WHICH audited judgements are "
                     "credited and in WHETHER the correction is applied to the clean state "
                     "as well. They are different estimands and must not be interchanged."),
            "frozen_primary_not_altered": sens["frozen_primary_not_altered"],
            "frozen_primary": sens["frozen_primary"],
            "measured_per_stratum_fn_rate": sens["measured_per_stratum_fn_rate"],
            "measured_false_negative_rate": sens["measured_false_negative_rate"],
            "scenarios": sens["scenarios"],
            "which_scenario_the_manuscript_quotes": {
                "conservative_one_sided": "one_sided_with_partial",
                "why": ("'Yes plus Partially credited on E0 only' is the outer bound of the "
                        "criticism and therefore the conservative choice."),
                "earlier_public_aggregate_used": "one_sided_strict",
                "these_are_not_in_conflict": True,
            },
            "symmetric_scenarios_are_modelled": (
                "The symmetric scenarios apply the measured E0 false-negative rate to E1 "
                "near misses as well. The E1 near misses were NEVER AUDITED. Symmetric "
                "figures are modelled, not measured."),
            "verdict": sens["verdict"],
        },
        "frontier": {
            # fr["summary"] carries BOTH providers; take the openai block so that
            # frontier.openai is the openai results and nothing else.
            "openai": fr["summary"].get("openai", fr["summary"]),
            "anthropic": {
                "model": anth["model"],
                "total_records": anth["total_records"],
                "binary_verdict_rung": anth["binary_verdict_rung"],
                "accuracy": anth["accuracy"],
                "finding_list_rungs": anth["finding_list_rungs"],
                "prose_sensitivity_parse": anth["prose_sensitivity_parse"],
                "reconciliation": anth["the_49_plus_8_reconciliation"],
                "what_was_not_done": anth["what_was_not_done"],
                "refusals_are_not_errors": (
                    "A refused or unparseable output is NOT a wrong answer. The strict "
                    "denominator counts only strictly parsed verdicts."),
            },
            "bootstrap": {"seed": fr["seed"], "draws": fr["n_bootstrap"]},
        },
        "gold_label_validation": {
            "label": "Human gold-label validation of the deterministic checkers",
            "human_participants": num("hv_participants"),
            "privacy": ("Aggregates only. No participant identifier, free text or "
                        "per-participant row is published."),
            "agreement_overall": frac("hv_agree"),
            "agreement_defective_items": frac("hv_def"),
            "agreement_control_items": frac("hv_ctrl"),
            "false_alarms_on_controls": frac("hv_falsealarm"),
            "evidence_cited": frac("hv_evidence"),
            "cohens_kappa": fn["hv_kappa"],
            "raw_agreement_pct": fn["hv_rawagree_pct"],
            "n_manuscripts": num("hv_manuscripts"),
            "n_relations": num("hv_relations"),
            "sensitivity_excluding_one_contested_item": {
                "item": fn["hv_sens_item"],
                "agreement_overall": frac("hv_sens_agree"),
                "agreement_defective_items": frac("hv_sens_def"),
                "agreement_control_items": frac("hv_sens_ctrl"),
            },
        },
        "denominator_reconciliation": den,
        "miss_anatomy": miss,
        "contamination_chronology": pseudonymise_chronology(chron, cmap),
        "audit_impact": imp,
        "generated_by": "tools/build_research_data.py",
    }


def manuscript_index():
    fn = J(ROOT / "paper_final/FINAL_NUMBERS.json")
    prov = J(ROOT / "paper_final/FINAL_PROVENANCE_MAP.json")["entries"]
    entries, unknown = {}, set()
    for macro, rec in sorted(prov.items()):
        srcs = [s.strip() for s in str(rec.get("source", "")).split(";") if s.strip()]
        routes, notes = set(), []
        for s in srcs:
            base = s.split("(")[0].strip().rstrip("*").split("/")[-1]
            hit = None
            for k, v in ROUTE.items():
                if base.startswith(k.split("*")[0][:18]) or k in s:
                    hit = v
                    break
            if hit is None:
                unknown.add(base)
                hit = ("unclassified", "no route recorded")
            routes.add(hit[0])
            notes.append(hit[1])
        route = ("mixed" if len(routes) > 1 else (routes.pop() if routes else "unclassified"))
        entries[macro] = {
            "value": rec.get("value"),
            "frozen_value": fn.get(macro),
            "canonical_source": srcs,
            "reproduction_route": route,
            "how": sorted(set(notes)),
        }
    if unknown:
        print("  WARNING unclassified sources:", sorted(unknown), file=sys.stderr)
    return {
        "schema_version": 1,
        "defects_are_synthetic": STMT_TEXT,
        "what_this_is": ("Source-of-truth manifest. Every manuscript macro, its frozen "
                         "value, the canonical record it came from, and how it can be "
                         "reproduced from the public release."),
        "routes": {
            "recomputable": "computable from the public data files in docs/data/",
            "audited_aggregate": ("carried as a published aggregate; the underlying "
                                  "observations cannot safely be released"),
            "restricted": "not published; see DATA_SHARING_AND_PRIVACY_REVIEW.md",
            "mixed": "parts of this value take different routes",
        },
        "n_macros": len(entries),
        "entries": entries,
        "generated_by": "tools/build_research_data.py",
    }


def write(name, doc):
    b = json.dumps(doc, indent=1).encode()
    (PUB / name).write_bytes(b)
    print(f"wrote docs/data/{name}  {len(b)} bytes  sha256 {hashlib.sha256(b).hexdigest()}")


def main() -> int:
    PUB.mkdir(parents=True, exist_ok=True)
    write("research_results.json", research_results())
    write("manuscript_results_index.json", manuscript_index())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
