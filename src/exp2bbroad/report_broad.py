"""Experiment 2B-broad reports. Every number comes from BroadEval.out (analysis.json)."""
from __future__ import annotations

import json

import evaluate as EV
import models_broad as MB

pct = EV.pct


def ci(t):
    return f"{100 * t['diff']:+.1f} pp [{100 * t['ci95'][0]:.1f}, {100 * t['ci95'][1]:.1f}]" if t["ci95"][0] is not None else "n/a"


def order(E):
    return sorted(E.models, key=lambda m: (MB.COMPETENCE_CLASS[m] != "primary", MB.MODELS[m]["family"], m))


def write(E):
    o, rd = E.out, E.rd
    ms = order(E)
    meta = o["model_meta"]

    # ---------------- integrity
    I = ["# Experiment 2B-broad — integrity report", "",
         "Records for the four 2B primaries are reused unchanged from `runs/exp2b_20260914_142911` (evidence, matrix) and",
         "`runs/exp2br_20260914_214259` (blind); the eight characterization models were run here with the identical frozen protocol.", "",
         "| Model | Family | Phase | Requested | Valid | Rate | Truncated | Schema | Parse | Empty | HTTP | Source |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in o["integrity"]["cells"]:
        I.append(f"| {c['model']} | {c['family']} | {c['phase']} | {c['requested']} | {c['valid']} | {100 * c['valid_rate']:.1f}% | "
                 f"{c['TRUNCATED']} | {c['INVALID_SCHEMA']} | {c['PARSE_FAILED']} | {c['EMPTY_CONTENT']} | {c['HTTP_FAILED']} | {c['source']} |")
    nf = o["matrix"]["noise_floor"]
    I += ["", "## Replicate (noise) floor — the matrix neutral arm repeats the evidence request byte-for-byte", "",
          f"Pooled: verdict agreement {pct(nf['verdict_agreement'])}, byte-identical {pct(nf['byte_identical'])}.", "",
          "| Model | Verdict agreement | Byte-identical |", "|---|---|---|"]
    for m in ms:
        v = o["matrix"]["noise_floor_by_model"][m]
        I.append(f"| {m} | {pct(v['verdict_agreement'])} | {pct(v['byte_identical'])} |")
    I += ["", "Per-model preflight (technical gate) results are in `exp2bbroad/results/preflight_<model>.json` and",
          "`exp2bbroad/VALIDATION_GATE.md`.", ""]
    (rd / "INTEGRITY_REPORT.md").write_text("\n".join(I) + "\n")

    # ---------------- broad family analysis
    A = ["# Broad-family characterization", "",
         "Competence classes come from the frozen eligibility bakeoff of Experiment 2B-family and are not recomputed here:",
         "`primary` = passed that gate (Qwen, Gemma); `characterization` = technically viable but did not pass it.",
         "All models solved the identical frozen task; differences below are observational, never causal.", "",
         "## Per model", "",
         "| Model | Family | B | Quant | Regime | Class | E0 | E1 | E2 | Trajectory | UNRESOLVED | Blind TRUE | H1 gap [95% CI] (p) | CV acc | CR acc | H3 helped/harmed (p) | Correct verdicts citing relation |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in ms:
        h2, bl, h1, mx, pv = o["h2"]["by_model"][m], o["blind"][m], o["h1"]["by_model"][m], o["matrix"]["by_model"][m], o["provenance"][m]
        h3 = mx["h3_correct_rationale_vs_correct_verdict"]
        A.append(f"| {m} | {meta[m]['family']} | {meta[m]['params_b']} | {meta[m]['quantization']} | {meta[m]['reasoning_mode']} | "
                 f"{meta[m]['competence_class']} | {pct(h2['E0_detection'])} | {pct(h2['E1_clearance'])} | {pct(h2['E2_detection'])} | "
                 f"{pct(h2['trajectory'])} | {pct(h2['unresolved_rate'])} | {pct(bl['true_rate'])} | {ci(h1)} ({h1['mcnemar_p']}) | "
                 f"{pct(mx['cv_acc'])} | {pct(mx['cr_acc'])} | {h3['helpful']}/{h3['harmful']} ({h3['mcnemar_p']}) | "
                 f"{pct(pv['correct_with_relation_support'])} |")
    for key, title in (("by_family", "family"), ("by_competence_class", "competence class"), ("by_reasoning_mode", "reasoning regime")):
        A += ["", f"## Pooled by {title}", "",
              "| Slice | Models | E0 | E1 | E2 | Trajectory | Blind TRUE | H1 targeted-only / blind-only | H1 gap [95% CI] (p) | H3 helped/harmed (p) |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for k, v in o["h2"][key].items():
            h1 = o["h1"][key][k]
            h3 = o["matrix"][key][k]["h3_correct_rationale_vs_correct_verdict"]
            A.append(f"| {k} | {', '.join(v['models'])} | {pct(v['E0_detection'])} | {pct(v['E1_clearance'])} | {pct(v['E2_detection'])} | "
                     f"{pct(v['trajectory'])} | {pct(h1['blind_rate'])} | {h1['first_only']} / {h1['second_only']} | {ci(h1)} ({h1['mcnemar_p']}) | "
                     f"{h3['helpful']}/{h3['harmful']} ({h3['mcnemar_p']}) |")
    A += ["", "## H1 — within-model discovery vs targeted confirmation", "",
          "Each row pairs the same 60 E0 manuscripts: targeted verification of the named relation vs blind audit of the same file.",
          "A within-model comparison does not require high absolute accuracy.", "",
          "| Model | n | Targeted | Blind | Both | Targeted only | Blind only | Neither | Gap [95% CI] | p | Qualitative H1 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in ms:
        t = o["h1"]["by_model"][m]
        q = t["first_only"] > t["second_only"] and t["mcnemar_p"] < 0.05
        A.append(f"| {m} | {t['n']} | {pct(t['targeted_rate'])} | {pct(t['blind_rate'])} | {t['both']} | {t['first_only']} | "
                 f"{t['second_only']} | {t['neither']} | {ci(t)} | {t['mcnemar_p']} | {'yes' if q else 'no'} |")
    A += ["", "## Blind discovery detail", "",
          "| Model | Valid | TRUE | PARTIAL | MISSED | Zero-finding | Finding counts | Clean-control false positives |",
          "|---|---|---|---|---|---|---|---|"]
    for m in ms:
        b = o["blind"][m]
        A.append(f"| {m} | {b['n_valid']} | {pct(b['true_rate'])} | {b['labels'].get('PARTIAL_DETECTION', 0)} | {b['labels'].get('MISSED', 0)} | "
                 f"{pct(b['zero_finding_rate'])} | {b['finding_counts']} | {sum(b['clean_false_positives'].values())} |")
    A += ["", "## Controlled exposure matrix (20 cases x 2 states x 6 arms)", "",
          "| Model | Neutral | Location | Correct verdict | Correct verdict+rationale | False verdict | False verdict+rationale | H3 [95% CI] (p) | False-verdict adoption | False-rationale adoption |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for m in ms:
        v = o["matrix"]["by_model"][m]
        h3, fv, fr = v["h3_correct_rationale_vs_correct_verdict"], v["false_verdict_vs_neutral"], v["false_rationale_vs_neutral"]
        A.append(f"| {m} | {pct(v['neutral_acc'])} | {pct(v['location_acc'])} | {pct(v['cv_acc'])} | {pct(v['cr_acc'])} | {pct(v['fv_acc'])} | "
                 f"{pct(v['fr_acc'])} | {ci(h3)} ({h3['mcnemar_p']}) | {pct(fv['adoption_when_neutral_disagreed'])} | "
                 f"{pct(fr['adoption_when_neutral_disagreed'])} |")
    A += ["", "## False priors (secondary)", "",
          "| Model | False verdict vs neutral: helped/harmed (p) | False rationale vs false verdict: helped/harmed (p) |", "|---|---|---|"]
    for m in ms:
        v = o["matrix"]["by_model"][m]
        fv, fr = v["false_verdict_vs_neutral"], v["false_rationale_vs_false_verdict"]
        A.append(f"| {m} | {fv['helpful']}/{fv['harmful']} ({fv['mcnemar_p']}) | {fr['helpful']}/{fr['harmful']} ({fr['mcnemar_p']}) |")
    (rd / "BROAD_FAMILY_ANALYSIS.md").write_text("\n".join(A) + "\n")

    # ---------------- provenance
    PV = ["# Evidence provenance audit (targeted trials)", "",
          "Verdict correctness and provenance validity are separate properties. GROUNDED = at least one cited line is an exact line of",
          "the tested relation; GROUNDED_VIA_ADJACENT = only through a blank line next to it; UNGROUNDED_VALID_LINES = only valid lines",
          "outside the relation; INVALID_ONLY = only nonexistent or malformed IDs; NO_CITATION = no IDs.", "",
          "| Model | Family | Class | Trials | GROUNDED | Via adjacent | Unrelated lines only | Invalid only | No citation | Correct verdicts citing the relation |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for m in ms:
        p = o["provenance"][m]
        c = p["classes"]
        PV.append(f"| {m} | {meta[m]['family']} | {meta[m]['competence_class']} | {p['trials']} | {c.get('GROUNDED', 0)} | "
                  f"{c.get('GROUNDED_VIA_ADJACENT', 0)} | {c.get('UNGROUNDED_VALID_LINES', 0)} | {c.get('INVALID_ONLY', 0)} | "
                  f"{c.get('NO_CITATION', 0)} | {pct(p['correct_with_relation_support'])} |")
    PV += ["", "By verdict correctness (trial classes):", ""]
    for m in ms:
        PV.append(f"- {m}: {o['provenance'][m]['by_verdict_correctness']}")
    (rd / "PROVENANCE_AUDIT.md").write_text("\n".join(PV) + "\n")

    # ---------------- error taxonomy
    T = ["# Error taxonomy", "",
         "Shares are over the 60 cases (or 180 targeted trials for UNRESOLVED / provenance rates, 60 audits for blind failure).",
         "Categories are not mutually exclusive; `dominant_error_mode` is the largest non-blind share.", "",
         "| Model | Family | Class | MISS_DEFECT | FALSE_ALARM_ON_REPAIR | MISS_REVERSAL | ALWAYS_NO_ISSUE | ALWAYS_ISSUE | EXCESS_UNRESOLVED | WRONG_EVIDENCE_BINDING | INVALID_PROVENANCE | BLIND_DISCOVERY_FAILURE | Dominant |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in ms:
        t = o["error_taxonomy"]["by_model"][m]
        s = t["shares"]
        T.append(f"| {m} | {meta[m]['family']} | {meta[m]['competence_class']} | " + " | ".join(
            pct(s[k]) for k in ("MISS_DEFECT", "FALSE_ALARM_ON_REPAIR", "MISS_REVERSAL", "ALWAYS_NO_ISSUE", "ALWAYS_ISSUE",
                                "EXCESS_UNRESOLVED", "WRONG_EVIDENCE_BINDING", "INVALID_PROVENANCE", "BLIND_DISCOVERY_FAILURE")) +
                 f" | {t['dominant_error_mode']} |")
    T += ["", "Dominant mode by family:", ""] + [f"- {k}: {v}" for k, v in o["error_taxonomy"]["dominant_by_family"].items()]
    (rd / "ERROR_TAXONOMY.md").write_text("\n".join(T) + "\n")

    # ---------------- report
    tot = {"requested": sum(c["requested"] for c in o["integrity"]["cells"] if c["source"] == "this run"),
           "valid": sum(c["valid"] for c in o["integrity"]["cells"] if c["source"] == "this run")}
    R = ["# Experiment 2B-broad — report", "",
         f"Run `{rd.name}`. {len(ms)} models from {len({meta[m]['family'] for m in ms})} independently developed families.",
         f"New inference in this run: {tot['requested']} requests, {tot['valid']} valid "
         f"({100 * tot['valid'] / tot['requested']:.1f}%). The four 2B primaries are reused, not rerun.", "",
         "The eligibility decision of `runs/exp2bfamily_20260915_152058` (REVISE_FAMILY_EXTENSION) is untouched: no model added here",
         "becomes a competent primary verifier.", "",
         "| Model | Family | Class | E0 | E1 | E2 | Trajectory | Blind TRUE | H1 p | H3 helped/harmed | Dominant error |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in ms:
        h2, bl, h1 = o["h2"]["by_model"][m], o["blind"][m], o["h1"]["by_model"][m]
        h3 = o["matrix"]["by_model"][m]["h3_correct_rationale_vs_correct_verdict"]
        R.append(f"| {m} | {meta[m]['family']} | {meta[m]['competence_class']} | {pct(h2['E0_detection'])} | {pct(h2['E1_clearance'])} | "
                 f"{pct(h2['E2_detection'])} | {pct(h2['trajectory'])} | {pct(bl['true_rate'])} | {h1['mcnemar_p']} | "
                 f"{h3['helpful']}/{h3['harmful']} | {o['error_taxonomy']['by_model'][m]['dominant_error_mode']} |")
    R += ["", "Detail: `BROAD_FAMILY_ANALYSIS.md`, `ERROR_TAXONOMY.md`, `PROVENANCE_AUDIT.md`, `INTEGRITY_REPORT.md`,",
          "`SCIENTIFIC_ASSESSMENT.md`, `NEXT_DECISION.md`; tables in `*.csv`; raw records in `*_trials.jsonl`.", ""]
    (rd / "REPORT.md").write_text("\n".join(R) + "\n")
    return o
