"""Experiment 3 held-out reports. Every number comes from HeldoutEval.out (analysis.json)."""
from __future__ import annotations

import json

import evaluate as EV

pct = EV.pct


def ci(t):
    return f"{100 * t['diff']:+.1f} pp [{100 * t['ci95'][0]:.1f}, {100 * t['ci95'][1]:.1f}]" \
        if t.get("ci95") and t["ci95"][0] is not None else "n/a"


def write(E):
    o, rd = E.out, E.rd
    ms = E.models
    meta = o["model_meta"]

    # ---------------- integrity
    I = ["# Experiment 3 held-out — integrity report", "",
         f"Held-out corpus: {len(o['papers'])} manuscripts, {o['n_cases']} native cases, "
         f"{len(o['domain_counts'])} domains. Primary models: {', '.join(ms)}.", "",
         "| Model | Phase | Requested | Valid | Rate | Truncated | Schema | Parse | Empty | HTTP | Not run |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in o["integrity"]["cells"]:
        I.append(f"| {c['model']} | {c['phase']} | {c['requested']} | {c['valid']} | {100 * c['valid_rate']:.1f}% | "
                 f"{c['TRUNCATED']} | {c['INVALID_SCHEMA']} | {c['PARSE_FAILED']} | {c['EMPTY_CONTENT']} | "
                 f"{c['HTTP_FAILED']} | {c['NOT_RUN']} |")
    nf = o["matrix"]["noise_floor"]
    I += ["", "Replicate floor (matrix neutral arm repeats the evidence request byte-for-byte): verdict agreement "
          f"{pct(nf['verdict_agreement'])}, byte-identical {pct(nf['byte_identical'])}.", "",
          "## Benchmark leakage audit", "",
          f"- Blind audits whose finding uses generic edit vocabulary on a target line: "
          f"{pct(o['leakage']['blind_generic_on_target'])}.",
          "- Targeted outputs containing generic edit vocabulary, by model and state:", ""]
    for k, v in sorted(o["leakage"]["targeted_generic_terms"].items()):
        I.append(f"  - {k}: {pct(v)}")
    I += ["", "Per-paper validity is in `integrity_by_paper.csv`; the dataset-side audit is "
          "`exp3heldout/CASE_AUDIT.md`.", ""]
    (rd / "INTEGRITY_REPORT.md").write_text("\n".join(I) + "\n")

    # ---------------- held-out generalization (H1 + H2 + H3 headline)
    h1, h2 = o["h1"], o["h2"]
    G = ["# Held-out generalization", "",
         "All numbers come from manuscripts that were never used to tune any prompt, schema, scorer, model choice or "
         "threshold. The protocol and the model set were frozen before the first held-out request.", "",
         "## H1 — discovery vs targeted confirmation", "",
         f"Pooled over {len(ms)} models x {o['n_cases']} cases: targeted {pct(h1['pooled']['targeted_rate'])} vs blind "
         f"{pct(h1['pooled']['blind_rate'])}; targeted-only {h1['pooled']['first_only']}, blind-only "
         f"{h1['pooled']['second_only']}; {ci(h1['pooled'])}, exact McNemar p={h1['pooled']['mcnemar_p']}.", "",
         "| Slice | n | Targeted | Blind | Both | T-only | B-only | Neither | Gap [95% CI] | p |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for grp, title in (("by_model", "model"), ("by_domain", "domain"), ("by_family", "defect family")):
        for k, t in o["h1"][grp].items():
            G.append(f"| {title}: {k} | {t['n']} | {pct(t['targeted_rate'])} | {pct(t['blind_rate'])} | {t['both']} | "
                     f"{t['first_only']} | {t['second_only']} | {t['neither']} | {ci(t)} | {t['mcnemar_p']} |")
    G += ["", "### Per manuscript", "", "| Paper | Domain | n | T-only | B-only | Gap [95% CI] | p |",
          "|---|---|---|---|---|---|---|"]
    for pid, t in o["h1"]["by_paper"].items():
        G.append(f"| {pid} | {o['domains'][pid]} | {t['n']} | {t['first_only']} | {t['second_only']} | {ci(t)} | "
                 f"{t['mcnemar_p']} |")
    lopo = o["h1"]["lopo"]
    diffs = [t["diff"] for t in lopo.values()]
    ps = [t["mcnemar_p"] for t in lopo.values()]
    G += ["", "### Leave-one-paper-out (H1 pooled, recomputed without each manuscript)", "",
          f"Effect size range {100 * min(diffs):+.1f} to {100 * max(diffs):+.1f} pp; p range {min(ps):.3g} to "
          f"{max(ps):.3g}; all {len(lopo)} subsets keep targeted-only > blind-only: "
          f"{all(t['first_only'] > t['second_only'] for t in lopo.values())}.", "",
          "| Omitted paper | T-only | B-only | Gap | p |", "|---|---|---|---|---|"]
    for pid, t in lopo.items():
        G.append(f"| {pid} | {t['first_only']} | {t['second_only']} | {ci(t)} | {t['mcnemar_p']} |")
    G += ["", "### Leave-one-domain-out and leave-one-defect-family-out", "",
          "| Omitted | Kind | T-only | B-only | Gap | p |", "|---|---|---|---|---|---|"]
    for d, t in o["h1"]["lodo"].items():
        G.append(f"| {d} | domain | {t['first_only']} | {t['second_only']} | {ci(t)} | {t['mcnemar_p']} |")
    for f, t in o["h1"]["lofo"].items():
        G.append(f"| {f} | defect family | {t['first_only']} | {t['second_only']} | {ci(t)} | {t['mcnemar_p']} |")
    G += ["", "## H2 — evidence responsiveness", "",
          "| Model | Class | E0 | E1 | E2 | Full trajectory | UNRESOLVED | Failures |", "|---|---|---|---|---|---|---|---|"]
    for m in ms:
        v = h2["by_model"][m]
        G.append(f"| {m} | {meta[m]['competence_class']} | {pct(v['E0_detection'])} | {pct(v['E1_clearance'])} | "
                 f"{pct(v['E2_detection'])} | {pct(v['trajectory'])} | {pct(v['unresolved_rate'])} | "
                 f"{pct(v['failure_rate'])} |")
    v = h2["pooled"]
    G.append(f"| POOLED | — | {pct(v['E0_detection'])} | {pct(v['E1_clearance'])} | {pct(v['E2_detection'])} | "
             f"{pct(v['trajectory'])} | {pct(v['unresolved_rate'])} | {pct(v['failure_rate'])} |")
    G += ["", "## H3 — correct-rationale transfer (pre-registered matrix subset)", "",
          f"Subset: {len(o['matrix']['subset_cases'])} cases, families {o['matrix']['subset_family_counts']}, "
          f"domains {o['matrix']['subset_domain_counts']}.", "",
          "| Model | Neutral | Location | Correct verdict | + rationale | False verdict | + rationale | "
          "H3 helped/harmed | H3 [95% CI] | p |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m in ms:
        x = o["matrix"]["by_model"][m]
        h3 = x["h3"]
        G.append(f"| {m} | {pct(x['neutral_acc'])} | {pct(x['location_acc'])} | {pct(x['cv_acc'])} | "
                 f"{pct(x['cr_acc'])} | {pct(x['fv_acc'])} | {pct(x['fr_acc'])} | {h3['helpful']}/{h3['harmful']} | "
                 f"{ci(h3)} | {h3['mcnemar_p']} |")
    p3 = o["matrix"]["pooled"]["h3"]
    G.append(f"| POOLED | {pct(o['matrix']['pooled']['neutral_acc'])} | "
             f"{pct(o['matrix']['pooled']['location_acc'])} | {pct(o['matrix']['pooled']['cv_acc'])} | "
             f"{pct(o['matrix']['pooled']['cr_acc'])} | {pct(o['matrix']['pooled']['fv_acc'])} | "
             f"{pct(o['matrix']['pooled']['fr_acc'])} | {p3['helpful']}/{p3['harmful']} | {ci(p3)} | "
             f"{p3['mcnemar_p']} |")
    G += ["", "## False priors (secondary)", "",
          "| Model | False verdict vs neutral helped/harmed (p) | adoption | False rationale vs false verdict "
          "helped/harmed (p) | adoption |", "|---|---|---|---|---|"]
    for m in ms:
        x = o["matrix"]["by_model"][m]
        fv, fr = x["false_verdict_vs_neutral"], x["false_rationale_vs_false_verdict"]
        G.append(f"| {m} | {fv['helpful']}/{fv['harmful']} ({fv['mcnemar_p']}) | "
                 f"{pct(fv['adoption_when_neutral_disagreed'])} | {fr['helpful']}/{fr['harmful']} "
                 f"({fr['mcnemar_p']}) | {pct(x['false_rationale_vs_neutral']['adoption_when_neutral_disagreed'])} |")
    G += ["", "## Blind discovery detail", "",
          "| Model | Valid | TRUE | PARTIAL | MISSED | Zero-finding | Finding counts | Clean-control FP relations |",
          "|---|---|---|---|---|---|---|---|"]
    for m in ms:
        b = o["blind"][m]
        G.append(f"| {m} | {b['n_valid']} | {pct(b['true_rate'])} | {b['partial']} | {b['missed']} | "
                 f"{pct(b['zero_finding_rate'])} | {b['finding_counts']} | "
                 f"{sum(b['clean_false_positive_relations'].values())} |")
    (rd / "HELDOUT_GENERALIZATION.md").write_text("\n".join(G) + "\n")

    # ---------------- domain analysis
    Dm = ["# Domain analysis", "",
          f"Cases per domain: {o['domain_counts']}. No verifier result influenced the corpus.", "",
          "| Domain | Cases | E0 | E1 | E2 | Trajectory | Blind TRUE | H1 T-only/B-only | H1 gap | p |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for d, v in o["h2"]["by_domain"].items():
        t = o["h1"]["by_domain"][d]
        Dm.append(f"| {d} | {o['domain_counts'][d]} | {pct(v['E0_detection'])} | {pct(v['E1_clearance'])} | "
                  f"{pct(v['E2_detection'])} | {pct(v['trajectory'])} | {pct(t['blind_rate'])} | "
                  f"{t['first_only']}/{t['second_only']} | {ci(t)} | {t['mcnemar_p']} |")
    Dm += ["", "## Leave-one-domain-out (H1)", "", "| Omitted domain | T-only | B-only | Gap | p |",
           "|---|---|---|---|---|"]
    for d, t in o["h1"]["lodo"].items():
        Dm.append(f"| {d} | {t['first_only']} | {t['second_only']} | {ci(t)} | {t['mcnemar_p']} |")
    Dm += ["", "## H2 by defect family (pooled over models)", "",
           "| Family | Cases | E0 | E1 | E2 | Trajectory |", "|---|---|---|---|---|---|"]
    for f, v in o["h2"]["by_family"].items():
        Dm.append(f"| {f} | {o['family_counts'].get(f)} | {pct(v['E0_detection'])} | {pct(v['E1_clearance'])} | "
                  f"{pct(v['E2_detection'])} | {pct(v['trajectory'])} |")
    Dm += ["", "## H3 by domain and family (matrix subset)", "", "| Slice | helped | harmed | diff | p |",
           "|---|---|---|---|---|"]
    for d, x in o["matrix"]["by_domain"].items():
        h3 = x["h3"]
        Dm.append(f"| domain {d} | {h3['helpful']} | {h3['harmful']} | {ci(h3)} | {h3['mcnemar_p']} |")
    for f, x in o["matrix"]["by_family"].items():
        h3 = x["h3"]
        Dm.append(f"| family {f} | {h3['helpful']} | {h3['harmful']} | {ci(h3)} | {h3['mcnemar_p']} |")
    (rd / "DOMAIN_ANALYSIS.md").write_text("\n".join(Dm) + "\n")

    # ---------------- hierarchical
    h = o["hierarchical"]
    H = ["# Hierarchical analysis", "",
         "The generations are clustered: domain -> manuscript -> case -> evidence state -> model. The transparent "
         "paired counts in `HELDOUT_GENERALIZATION.md` remain the primary statistics; the models below test whether "
         "the H1 and H3 contrasts survive manuscript- and case-level clustering.", "",
         f"Observations {h['n_observations']} (H1 design: one row per model x case x condition), cases "
         f"{h['n_cases']}, manuscripts {h['n_papers']}, models {h['n_models']}.", "",
         "## H1: GEE logistic regression, exchangeable correlation, clustered by manuscript", ""]
    g = h.get("gee_cluster_paper", {})
    if "error" in g:
        H.append(f"Not estimable: {g['error']}")
    else:
        H += [f"- formula: `{g['formula']}`",
              f"- blind condition coefficient {g['blind_coef']:.3f} (SE {g['blind_se']:.3f}, z {g['blind_z']:.2f}, "
              f"p {g['blind_p']:.3g})",
              f"- odds ratio for detecting the defect when auditing blind rather than answering the targeted "
              f"question: {g['blind_odds_ratio']:.3f} [{g['blind_or_ci95'][0]:.3f}, {g['blind_or_ci95'][1]:.3f}]",
              f"- clusters (manuscripts): {g['n_clusters']}"]
    b = h.get("bayes_mixed_glm", {})
    H += ["", "## H1: Bayesian mixed GLM with random intercepts for manuscript and case", ""]
    if "error" in b:
        H.append(f"Not estimable: {b['error']}")
    else:
        H += [f"- formula: `{b['formula']}`",
              f"- blind posterior mean {b['blind_posterior_mean']:.3f} (SD {b['blind_posterior_sd']:.3f}); "
              f"odds ratio {b['blind_odds_ratio']:.3f} [{b['blind_or_ci95'][0]:.3f}, {b['blind_or_ci95'][1]:.3f}]",
              f"- random-effect SDs: {b['random_effect_sd']}"]
    h3g = h.get("h3_gee_cluster_paper", {})
    H += ["", "## H3: GEE logistic regression clustered by manuscript", ""]
    if "error" in h3g:
        H.append(f"Not estimable: {h3g['error']}")
    else:
        H += [f"- rationale coefficient {h3g['rationale_coef']:.3f} (SE {h3g['rationale_se']:.3f}, "
              f"p {h3g['rationale_p']:.3g}); odds ratio {h3g['rationale_odds_ratio']:.3f}",
              f"- observations {h3g['n_observations']}"]
    H += ["", "Assumptions: GEE gives population-averaged effects with cluster-robust standard errors and does not "
          "require the random-effect distribution to be correct; the Bayesian mixed GLM is fitted by variational "
          "Bayes, so its interval is approximate. Model, defect family and domain enter as fixed effects; the "
          "condition contrast (blind vs targeted) is within case and within model.", ""]
    (rd / "HIERARCHICAL_ANALYSIS.md").write_text("\n".join(H) + "\n")

    # ---------------- broad family
    bf = o["broad_family"]
    B = ["# Broad-family held-out replication", "",
         f"Pre-registered subset of {bf['n_cases']} held-out cases (families {bf['subset_family_counts']}, domains "
         f"{bf['subset_domain_counts']}) run on all {len(E.broad_models)} models of Experiment 2B-broad: E0/E1/E2 "
         "targeted plus blind E0. Competence classes come from the frozen eligibility bakeoff and are not "
         "recomputed.", "",
         "| Model | Family | B | Class | E0 | E1 | E2 | Trajectory | Blind TRUE | H1 T-only/B-only (p) | "
         "Correct verdicts citing relation | MISS_REVERSAL |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in E.broad_models:
        v = bf["by_model"][m]
        h2m, h1m = v["h2"], v["h1"]
        B.append(f"| {m} | {meta[m]['family']} | {meta[m]['params_b']} | {meta[m]['competence_class']} | "
                 f"{pct(h2m['E0_detection'])} | {pct(h2m['E1_clearance'])} | {pct(h2m['E2_detection'])} | "
                 f"{pct(h2m['trajectory'])} | {pct(v['blind_true_rate'])} | "
                 f"{h1m['first_only']}/{h1m['second_only']} ({h1m['mcnemar_p']}) | "
                 f"{pct(v['correct_with_relation_support'])} | {pct(v['miss_reversal_rate'])} |")
    B += ["", "Questions asked of this subset (descriptive; capability and regime are confounded across models):",
          "1. H1 direction across families — see the H1 columns above.",
          "2. H2 as a capability discriminator — compare trajectory between primary and characterization classes.",
          "3. MISS_REVERSAL prevalence — last column.",
          "4. Provenance variation — 'correct verdicts citing relation'.",
          "5. Parameter scale vs competence — compare the B column with trajectory.", ""]
    (rd / "BROAD_FAMILY_HELDOUT.md").write_text("\n".join(B) + "\n")

    # ---------------- taxonomy and provenance
    T = ["# Error taxonomy (held-out)", "",
         "| Model | MISS_DEFECT | FALSE_ALARM_ON_REPAIR | MISS_REVERSAL | ALWAYS_NO_ISSUE | ALWAYS_ISSUE | "
         "EXCESS_UNRESOLVED | WRONG_EVIDENCE_BINDING | INVALID_PROVENANCE | BLIND_DISCOVERY_FAILURE | Dominant |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in ms:
        s = o["error_taxonomy"]["by_model"][m]["shares"]
        T.append(f"| {m} | " + " | ".join(pct(s[k]) for k in
                 ("MISS_DEFECT", "FALSE_ALARM_ON_REPAIR", "MISS_REVERSAL", "ALWAYS_NO_ISSUE", "ALWAYS_ISSUE",
                  "EXCESS_UNRESOLVED", "WRONG_EVIDENCE_BINDING", "INVALID_PROVENANCE", "BLIND_DISCOVERY_FAILURE")) +
                 f" | {o['error_taxonomy']['by_model'][m]['dominant_error_mode']} |")
    T += ["", "MISS_REVERSAL (E2 not detected) by domain, pooled over primary models:", ""]
    for d, v in o["error_taxonomy"]["miss_reversal_by_domain"].items():
        T.append(f"- {d}: {pct(v)}")
    (rd / "ERROR_TAXONOMY.md").write_text("\n".join(T) + "\n")

    PV = ["# Evidence provenance audit (held-out)", "",
          "Verdict correctness and provenance validity are separate properties.", "",
          "| Model | Trials | GROUNDED | Via adjacent | Unrelated lines only | Invalid only | No citation | "
          "Correct verdicts citing the relation |", "|---|---|---|---|---|---|---|---|"]
    for m in ms:
        p = o["provenance"][m]
        c = p["classes"]
        PV.append(f"| {m} | {p['trials']} | {c.get('GROUNDED', 0)} | {c.get('GROUNDED_VIA_ADJACENT', 0)} | "
                  f"{c.get('UNGROUNDED_VALID_LINES', 0)} | {c.get('INVALID_ONLY', 0)} | {c.get('NO_CITATION', 0)} | "
                  f"{pct(p['correct_with_relation_support'])} |")
    PV += ["", "Trial classes split by verdict correctness:", ""]
    for m in ms:
        PV.append(f"- {m}: {o['provenance'][m]['by_verdict_correctness']}")
    (rd / "PROVENANCE_AUDIT.md").write_text("\n".join(PV) + "\n")

    # ---------------- report
    tot_req = sum(c["requested"] for c in o["integrity"]["cells"])
    tot_val = sum(c["valid"] for c in o["integrity"]["cells"])
    t1 = h1["pooled"]
    R = ["# Experiment 3 — held-out generalization study", "",
         f"Run `{rd.name}`. Held-out corpus: {len(o['papers'])} manuscripts, {o['n_cases']} mechanically verified "
         f"native cases, {len(o['domain_counts'])} scientific domains, 6 defect families. "
         f"{tot_req} planned generations, {tot_val} valid ({100 * tot_val / max(1, tot_req):.1f}%).", "",
         f"**H1 pooled:** targeted {pct(t1['targeted_rate'])} vs blind {pct(t1['blind_rate'])}; "
         f"{t1['first_only']} targeted-only vs {t1['second_only']} blind-only; {ci(t1)}, p={t1['mcnemar_p']}.",
         f"**H2 pooled:** E0 {pct(h2['pooled']['E0_detection'])}, E1 {pct(h2['pooled']['E1_clearance'])}, "
         f"E2 {pct(h2['pooled']['E2_detection'])}, full trajectory {pct(h2['pooled']['trajectory'])}.",
         f"**H3 pooled (matrix subset):** helped {p3['helpful']}, harmed {p3['harmful']}, {ci(p3)}, "
         f"p={p3['mcnemar_p']}.", "",
         "| Model | Class | E0 | E1 | E2 | Trajectory | Blind TRUE | H1 p | H3 helped/harmed | Dominant error |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for m in ms:
        v, b, t = h2["by_model"][m], o["blind"][m], h1["by_model"][m]
        h3 = o["matrix"]["by_model"][m]["h3"]
        R.append(f"| {m} | {meta[m]['competence_class']} | {pct(v['E0_detection'])} | {pct(v['E1_clearance'])} | "
                 f"{pct(v['E2_detection'])} | {pct(v['trajectory'])} | {pct(b['true_rate'])} | {t['mcnemar_p']} | "
                 f"{h3['helpful']}/{h3['harmful']} | "
                 f"{o['error_taxonomy']['by_model'][m]['dominant_error_mode']} |")
    R += ["", "Reports: `HELDOUT_GENERALIZATION.md`, `DOMAIN_ANALYSIS.md`, `HIERARCHICAL_ANALYSIS.md`, "
          "`BROAD_FAMILY_HELDOUT.md`, `ERROR_TAXONOMY.md`, `PROVENANCE_AUDIT.md`, `INTEGRITY_REPORT.md`, "
          "`SCIENTIFIC_ASSESSMENT.md`, `NEXT_DECISION.md`. Tables: `*.csv`. Raw records: `*_trials.jsonl`.", ""]
    (rd / "REPORT.md").write_text("\n".join(R) + "\n")
    return o
