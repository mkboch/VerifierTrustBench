#!/usr/bin/env python3
"""Derive the playground's public sufficient statistics from the frozen private analysis artifacts.

This script is published so the derivation is auditable. Its *inputs* are not published: they live in the
private research tree and are passed with --private-root. Running it is only possible for someone who holds
those artifacts; everyone else can read it to see exactly what was extracted.

What it emits: numerators, denominators, paired discordant counts, condition labels.
What it never emits: per-case records, model generations, manuscript text, free-text rationales,
participant data of any kind.

    python tools/build_public_statistics.py --private-root /path/to/VerifierTrustBench \
                                            --out docs/data/public_sufficient_statistics.json
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, sys

MODELS = [
    ("qwen38_27", "Qwen3.8-27B"), ("qwen36_27", "Qwen3.6-27B"), ("gemma4_12", "Gemma-4-12B"),
    ("granite42_30", "Granite-4.2-30B"), ("qwen3_8", "Qwen3-8B"),
]
FAMILIES = ["arithmetic", "claim_evidence", "cross_reference", "method_result", "numerical", "statistical"]
DOMAINS = ["A_ml_ai", "B_vision_signal", "C_biomedical", "D_statistics", "E_physics_engineering"]
DOMAIN_LABEL = {"A_ml_ai": "ML / AI", "B_vision_signal": "Vision & signal", "C_biomedical": "Biomedical",
                "D_statistics": "Statistics", "E_physics_engineering": "Physics & engineering"}
ARM_LABEL = {
    "neutral": "Neutral control", "filler": "Length-matched filler", "correct_verdict": "Correct verdict only",
    "correct_rationale": "Correct rationale", "false_verdict": "False verdict only",
    "false_rationale": "False rationale", "cv_irrelevant": "Correct verdict + irrelevant text",
    "fv_irrelevant": "False verdict + irrelevant text",
}

def xn(d: dict) -> dict:
    """Keep only numerator and denominator from a rate block."""
    return {"x": int(d["x"]), "n": int(d["n"])}

def paired(d: dict) -> dict:
    """Keep only the 2x2 paired cell counts. b and c are sufficient for exact McNemar."""
    return {"n": int(d["n"]), "both": int(d["both"]), "b": int(d["first_only"]),
            "c": int(d["second_only"]), "neither": int(d["neither"])}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-root", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    a = ap.parse_args()
    R = a.private_root

    EXP3 = json.loads((R / "runs/exp3heldout_20260918_014959/analysis.json").read_text())
    PROF = json.loads((R / "nature_extension/phase0_methods/profile_exp3/profile.json").read_text())
    P3 = json.loads((R / "runs/natureext_phase3_latest/phase3_analysis.json").read_text())
    P4 = json.loads((R / "runs/natureext_phase4_latest/phase4_analysis.json").read_text())

    out: dict = {
        "schema_version": 1,
        "what_this_is": (
            "Minimal de-identified aggregate sufficient statistics for the VerifierTrustBench interactive "
            "playground. Counts only. No per-case records, no model outputs, no manuscript text, no "
            "human-participant data."
        ),
        "recomputation_note": (
            "Paired contrasts ship as the 2x2 cell counts (both, b, c, neither). The browser recomputes the "
            "difference and the exact two-sided McNemar p from b and c; nothing is precomputed for display."
        ),
        "models": [{"id": m, "label": lab} for m, lab in MODELS],
        "experiments": {},
    }

    # ---- 1. discovery vs relation-localized ------------------------------------------------
    h1 = EXP3["h1"]
    def h1block(d):
        return {**paired(d), "targeted": xn(d["targeted_rate"]), "blind": xn(d["blind_rate"])}
    out["experiments"]["discovery_vs_localized"] = {
        "label": "Discovery vs relation-localized verification",
        "unit": "paired case x model",
        "pooled": h1block(h1["pooled"]),
        "by_model": {m: h1block(h1["by_model"][m]) for m, _ in MODELS if m in h1["by_model"]},
        "by_family": {f: h1block(h1["by_family"][f]) for f in FAMILIES if f in h1["by_family"]},
        "by_domain": {d: h1block(h1["by_domain"][d]) for d in DOMAINS if d in h1["by_domain"]},
        "domain_labels": DOMAIN_LABEL,
    }

    # ---- 2. ranking: Recall@k, only the k values the finding budget makes observable --------
    ks = [str(k) for k in (1, 2, 3, 5)]
    out["experiments"]["ranking"] = {
        "label": "Does a longer finding list recover the missed defects?",
        "ks_observable": [int(k) for k in ks],
        "ks_note": PROF.get("ks_note", ""),
        "budget_note": (
            "The blind response schema caps a system at five findings, so only the recorded top-five budget "
            "is observable. Recall@4 was not stored separately and Recall@10 is not recoverable. No claim is "
            "made about ranks beyond five."
        ),
        "by_model": {
            m: {k: xn(PROF["by_model"][m]["discovery"]["recall_at"][k]) for k in ks}
            for m, _ in MODELS if m in PROF["by_model"]
        },
    }

    # ---- 3. agentic search -----------------------------------------------------------------
    am = P3["by_model"]["qwen38_27"]
    out["experiments"]["agentic"] = {
        "label": "Bounded agentic navigation",
        "model": "qwen38_27",
        "scope_note": (
            "One system under one bounded tool budget. Bounded agentic navigation recovered part of the "
            "observed direct-to-localized deficit. The unrecovered portion is not characterized."
        ),
        "n_paired_cases": int(am["n_paired_cases"]),
        "direct_blind": xn(am["direct_discovery"]),
        "agentic_blind": xn(am["agentic_discovery"]),
        "relation_localized": xn(EXP3["h1"]["by_model"]["qwen38_27"]["targeted_rate"]),
        "paired_agentic_vs_direct": paired(am["paired_agentic_vs_direct"]),
        "false_positive_findings_per_case": {
            "direct": am["false_positive_findings_per_case"]["direct"],
            "agentic": am["false_positive_findings_per_case"]["agentic"],
        },
        "tool_calls": {"mean": am["tool_calls"]["mean"],
                       "budget": max(int(k) for k in am["tool_calls"]["distribution"]),
                       "distribution": {str(k): int(v) for k, v in am["tool_calls"]["distribution"].items()}},
        "recall_at": {
            "agentic": {k: xn(am["agentic_curve"]["recall_at"][k]) for k in ks},
            "direct": {k: xn(am["direct_curve"]["recall_at"][k]) for k in ks},
        },
    }

    # ---- 4. information transfer (H3 control arms) -----------------------------------------
    arms = P4["arm_accuracy_pooled"]
    contrasts = {}
    for key, c in P4["results"].items():
        contrasts[key] = {
            "question": c["question"], "a_arm": c["a_arm"], "b_arm": c["b_arm"],
            **paired(c["pooled"]),
            "frozen_exact_p": c["pooled"].get("exact_p"),
            "frozen_ci95_pp": [round(100 * v, 2) for v in c["pooled"]["ci95"]],
        }
    out["experiments"]["information_transfer"] = {
        "label": "What transfers between verifiers",
        "arm_labels": ARM_LABEL,
        "arms": {k: xn(v) for k, v in arms.items()},
        "frozen_contrasts": contrasts,
        "null_note": (
            "A contrast whose interval includes zero is not evidence that the effect is exactly zero; it is "
            "an interval consistent with no effect at this sample size."
        ),
    }

    # ---- 5. Verification Evidence Profile ---------------------------------------------------
    prof = {}
    for m, _ in MODELS:
        if m not in PROF["by_model"]:
            continue
        d = PROF["by_model"][m]
        r = d["responsiveness"]
        n_resp = int(r["complete"])
        prof[m] = {
            "discovery_recall_at_1": xn(d["discovery"]["recall_at"]["1"]),
            "discovery_recall_at_5": xn(d["discovery"]["recall_at"]["5"]),
            "relation_localized": xn(EXP3["h1"]["by_model"][m]["targeted_rate"]),
            "false_alarm": xn(d["false_alarm_rate"]),
            "verdict_x_provenance": {k: int(v) for k, v in d["verdict_x_provenance"].items()},
            "trajectory": {"x": int(r["trajectory"]), "n": n_resp},
            "miss_defect": {"x": int(r["MISS_DEFECT"]), "n": n_resp},
            "miss_reversal": {"x": int(r["MISS_REVERSAL"]), "n": n_resp},
        }
    out["experiments"]["evidence_profile"] = {
        "label": "Verification Evidence Profile",
        "by_model": prof,
        "definitions": {
            "false_alarm": "1 - clearance on unmodified valid relations",
            "trajectory": "all three evidence states (E0, E1, E2) judged correctly on the same relation",
            "verdict_x_provenance": "verdict correctness crossed with whether the cited line carries the tested relation",
        },
    }

    # ---- human validation is deliberately absent -------------------------------------------
    out["human_validation"] = {
        "included": False,
        "reason": (
            "Omitted from the first public release. The human study involved six identifiable colleagues; no "
            "aggregate is published here so that no reconstruction path exists."
        ),
    }

    a.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, indent=1, sort_keys=False) + "\n"
    a.out.write_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    print(f"wrote {a.out}  {len(text)} bytes  sha256 {digest}")

    # fail loudly if anything long and prose-like slipped in
    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items(): yield from walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o): yield from walk(v, f"{path}[{i}]")
        else:
            yield path, o
    LONG_OK = {".what_this_is", ".recomputation_note", ".human_validation.reason"}
    for p, v in walk(out):
        if isinstance(v, str) and len(v) > 220 and p not in LONG_OK and not p.endswith(("_note", "question")):
            print(f"REFUSING: long string at {p}", file=sys.stderr); return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
