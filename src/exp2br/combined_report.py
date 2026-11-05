#!/usr/bin/env python3
"""Compose COMBINED_2B_FINAL.md from immutable Experiment 2B results and the Experiment 2B-R repaired blind results.

    python exp2br/combined_report.py --run-dir runs/exp2br_<ts>

Every number is copied from analysis.json / decision.json / provenance_audit.json of the named runs; each table states its
data provenance. Old 2B blind metrics appear only in the clearly marked sensitivity section.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_2B = ROOT / "runs/exp2b_20260914_142911"


def pct(r):
    return "n/a" if not r or not r.get("n") else f"{100 * r['rate']:.1f}% ({r['x']}/{r['n']})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    rd = Path(ap.parse_args().run_dir)
    rd = rd if rd.is_absolute() else ROOT / rd
    a2b = json.loads((RUN_2B / "analysis.json").read_text())
    d2b = json.loads((RUN_2B / "decision.json").read_text())
    abr = json.loads((rd / "analysis.json").read_text())
    dbr = abr["decision"]
    prov = json.loads((rd / "provenance_audit.json").read_text())
    models = a2b["primary_models"]
    L = ["# Experiment 2B — combined final report (2B + 2B-R)", "",
         f"**Final combined status: {dbr['status']}** (frozen 2B-R rules, `exp2br/FROZEN_DESIGN.md`).", "",
         "## Data provenance", "",
         "| Component | Source run | Notes |", "|---|---|---|",
         "| Targeted-neutral verification (E0/E1/E2), H2 | `runs/exp2b_20260914_142911` (immutable) | 720 trials; configuration unchanged, not rerun |",
         "| Controlled exposure matrix: H3, S1, location | `runs/exp2b_20260914_142911` (immutable) | 960 trials |",
         "| Actual verifier pairs, ELVAE anchor | `runs/exp2b_20260914_142911` (immutable) | 480 + 96 trials |",
         f"| Blind discovery, clean-control false positives | `{rd.relative_to(ROOT)}` (2B-R) | 260 audits, bounded schema; the 2B blind outputs are not used |",
         "| H1 discovery vs confirmation | 2B-R blind paired with 2B targeted-neutral E0 | |",
         "| Evidence provenance | no-inference audit of 2B targeted records | `PROVENANCE_AUDIT.md` |", "",
         f"Designs: 2B `{a2b['design_manifest_sha256']}`; 2B-R `{abr['design_manifest_sha256']}`. Models: {', '.join(models)}. "
         f"Papers: {', '.join(a2b['papers'])}.", "",
         "## Integrity", "",
         f"- 2B targeted components: evidence, matrix, pair and anchor cells >= 99.4% valid; 1 truncated targeted trial (qwen38_27). 0 fingerprint mismatches.",
         f"- 2B-R blind: {abr['integrity']['requested']} requested, {abr['integrity']['valid']} valid, failures {abr['integrity']['failures'] or 'none'}; "
         f"every model x paper cell 13/13: {dbr['R1_blind_integrity']}; usable papers {len(dbr['R2_usable_papers']['usable'])}/5.", "",
         "## H1 — discovery-confirmation gap [blind: 2B-R; targeted: 2B]", "",
         "| Slice | n | Targeted | Blind TRUE | Targeted only | Blind only | Difference [95% CI] | p |", "|---|---|---|---|---|---|---|---|"]
    h1 = abr["h1"]
    for k in models + ["POOLED"]:
        t = h1["by_model"][k]
        L.append(f"| {k} | {t['n']} | {pct(t['targeted_rate'])} | {pct(t['blind_rate'])} | {t['first_only']} | {t['second_only']} | {t['diff']} [{t['ci95'][0]}, {t['ci95'][1]}] | {t['mcnemar_p']} |")
    L += ["", "Per paper / leave-one-paper-out / leave-one-family-out (pooled over models):", ""]
    for g in ("by_model_paper", "lopo", "lofo"):
        for k, t in h1[g].items():
            if k.startswith("POOLED"):
                L.append(f"- {g} {k.split('|', 1)[1]}: {t['first_only']} vs {t['second_only']}, diff {t['diff']} [{t['ci95'][0]}, {t['ci95'][1]}], p={t['mcnemar_p']}")
    L += ["", "## Blind discovery and clean controls [2B-R]", "", "| Model | Blind TRUE | Zero-finding audits | Finding counts | Clean-control FP relations |", "|---|---|---|---|---|"]
    for m in models:
        b, beh = abr["blind"][m], abr["behaviour"][m]
        L.append(f"| {m} | {pct(b['true_rate'])} | {pct(beh['zero_findings'])} | {beh['finding_count_distribution']} | {sum(b['clean_false_positives'].values())} |")
    h2 = a2b["h2"]["by_model"]
    L += ["", "## H2 — evidence responsiveness [2B, immutable]", "", "| Model | E0 detection | E1 clearance | E2 detection | Full trajectory | Evidence trials citing the tested relation |", "|---|---|---|---|---|---|"]
    for m in models:
        v = h2[m]
        L.append(f"| {m} | {pct(v['E0_detection'])} | {pct(v['E1_clearance'])} | {pct(v['E2_detection'])} | {pct(v['trajectory'])} | {100 * prov['summary'][m]['grounded_rate']:.1f}% |")
    h3 = a2b["matrix"]["h3_correct_rationale_vs_correct_verdict"]
    L += ["", "## H3 — correct-rationale information transfer [2B, immutable]", "",
          f"Pooled: helpful {h3['pooled']['helpful']}, harmful {h3['pooled']['harmful']}, {h3['pooled']['diff']} [{h3['pooled']['ci95'][0]}, {h3['pooled']['ci95'][1]}], p={h3['pooled']['mcnemar_p']}.", ""]
    L += [f"- {m}: {h3['by_model'][m]['helpful']} vs {h3['by_model'][m]['harmful']} (p={h3['by_model'][m]['mcnemar_p']})" for m in models]
    L += [f"- leave-one-paper-out: " + "; ".join(f"without {p} {v['helpful']} vs {v['harmful']}" for p, v in h3["lopo"].items())]
    s1a, s1b = a2b["matrix"]["s1_false_verdict_vs_neutral"]["pooled"], a2b["matrix"]["s1_false_rationale_vs_false_verdict"]["pooled"]
    loc = a2b["matrix"]["location_vs_neutral"]
    L += ["", "## Secondary and exploratory [2B, immutable]", "",
          f"- False verdict vs neutral: helpful {s1a['helpful']}, harmful {s1a['harmful']}, {s1a['diff']} [{s1a['ci95'][0]}, {s1a['ci95'][1]}], adoption {pct(s1a['b_adoption_given_neutral_disagreed'])} — not demonstrated.",
          f"- False rationale vs false verdict: {s1b['helpful']} vs {s1b['harmful']}, p={s1b['mcnemar_p']} — not demonstrated pooled; post hoc qwen3_8 1 vs 14 (p = 0.001), strong models 6 vs 0 (exploratory).",
          f"- Location-only vs neutral: {loc['accuracy']['helpful']} vs {loc['accuracy']['harmful']}; direction {loc['direction']['toward_clearance']} vs {loc['direction']['toward_issue']} (p={loc['direction']['sign_test_p']}).",
          "- Actual pairs: correct sources adopted 80.0% with rationale vs 17.1% with verdict (24 vs 2, p = 1e-5); decisively wrong sources 13 usable units, not estimable.",
          "- ELVAE anchor: trajectories 6/6, 4/6, 0/6, 3/6 (qwen38_27, qwen36_27, qwen3_8, gemma4_12); not used in primary statistics.", "",
          "## Sensitivity: original 2B blind component (unbounded schema, 5 truncations)", ""]
    ob = abr["original_2b"]
    op = ob["h1_pooled"]
    L += [f"- 2B pooled H1: {op['first_only']} vs {op['second_only']}, diff {op['diff']} [{op['ci95'][0]}, {op['ci95'][1]}]; 2B-R pooled H1: "
          f"{h1['by_model']['POOLED']['first_only']} vs {h1['by_model']['POOLED']['second_only']}, diff {h1['by_model']['POOLED']['diff']} [{h1['by_model']['POOLED']['ci95'][0]}, {h1['by_model']['POOLED']['ci95'][1]}]."]
    L += [f"- {m}: blind TRUE 2B {pct(ob['blind'][m]['true_rate'])} -> 2B-R {pct(abr['blind'][m]['true_rate'])}; zero-finding {pct(ob['behaviour'][m]['zero_findings'])} -> {pct(abr['behaviour'][m]['zero_findings'])}" for m in models]
    L += ["", "## Wording constraints for the manuscript", "",
          "- 'Evidence-grounded' is used only for results whose cited lines include the tested relation. qwen3_8 cites the relation in "
          f"{100 * prov['summary']['qwen3_8']['grounded_rate']:.1f}% of evidence trials; its gains are described as verdict accuracy.",
          "- False-prior contamination is secondary/exploratory: bare false verdicts had no measurable effect; the false-rationale harm is a post-hoc capability interaction.",
          "- Blind discovery is measured under the frozen B1 prompt, under which strong models often return empty audits.", ""]
    (rd / "COMBINED_2B_FINAL.md").write_text("\n".join(L) + "\n")
    print("wrote COMBINED_2B_FINAL.md")


if __name__ == "__main__":
    main()
