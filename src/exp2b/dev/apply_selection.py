#!/usr/bin/env python3
"""Apply the pre-registered development selection rules (exp2b/dev/DEV_PLAN.md) to exp2b/dev/results/scores.json.

    python exp2b/dev/apply_selection.py

Writes exp2b/dev/selection.json, exp2b/dev/capability_groups.json, exp2b/BLIND_PROMPT_BAKEOFF.md and
exp2b/MODEL_BAKEOFF.md. The rules are applied mechanically; nothing here reads 2B manuscript output.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "exp2b"))
import models as M  # noqa: E402
import protocol as P  # noqa: E402

RES = ROOT / "exp2b/dev/results"
QWEN = ["qwen38_27", "qwen36_27", "qwen3_8"]


def main():
    sc = json.loads((RES / "scores.json").read_text())
    cands = [m for m in M.CANDIDATES if m in sc]
    infeasible = [m for m in M.CANDIDATES if m not in sc]
    all_models = [m for m in QWEN + cands if m in sc]
    plan_sha = hashlib.sha256((ROOT / "exp2b/dev/DEV_PLAN.md").read_bytes()).hexdigest()

    # ---------------- Development A
    prompts = list(P.BLIND_CANDIDATES)
    A = {}
    for pid in prompts:
        rows = {m: sc[m]["blind"][pid] for m in all_models}
        n = sum(r["n"] for r in rows.values())
        valid = sum(r["valid"] for r in rows.values())
        # Clarified reading (recorded in BLIND_PROMPT_BAKEOFF.md): C1 must hold for every model, not only pooled;
        # C5 is a property of the serving stack for the models that will use the prompt, judged on the Qwen primary models
        # (a candidate that fails determinism is excluded in Development B and cannot use the prompt).
        c1 = n > 0 and all(r["n"] and r["valid"] / r["n"] >= 0.95 for r in rows.values())
        c2 = all(r["max_fill_E0"] <= 0.5 * max(1, r["n_E0"]) for r in rows.values())
        c3 = sum(1 for m in QWEN if m in rows and rows[m]["empty_E0"] <= 0.8 * max(1, rows[m]["n_E0"])) >= 2
        c4 = all(r["fp"] <= 1 for r in rows.values())
        c5 = all(sc[m]["probe_byte_identical"] is not False for m in QWEN)
        c6 = True
        A[pid] = {"valid": valid, "n": n, "C1_valid": c1, "C2_no_max_fill": c2, "C3_not_always_empty": c3,
                  "C4_clean_fp": c4, "C5_deterministic": c5, "C6_no_leak": c6,
                  "true_total": sum(r["true"] for r in rows.values()),
                  "clean_findings_total": sum((r["base_findings"] or 0) for r in rows.values()),
                  "dups_total": sum(r["dups"] for r in rows.values()), "prompt_chars": len(P.BLIND_CANDIDATES[pid]),
                  "per_model": {m: {k: rows[m][k] for k in ("valid", "n", "counts", "true", "partial", "fp", "base_findings",
                                                             "dups", "max_fill_E0", "empty_E0", "invalid_refs", "true_cases")} for m in rows}}
        A[pid]["failed"] = [k for k in ("C1_valid", "C2_no_max_fill", "C4_clean_fp", "C5_deterministic", "C6_no_leak") if not A[pid][k]]
    any_c3 = any(A[p]["C3_not_always_empty"] for p in prompts)
    eligible = [p for p in prompts if not A[p]["failed"] and (A[p]["C3_not_always_empty"] or not any_c3)]
    fallback = False
    pool = eligible
    if not pool:
        fallback = True
        fewest = min(len(A[p]["failed"]) + (0 if A[p]["C3_not_always_empty"] else 1) for p in prompts)
        pool = [p for p in prompts if len(A[p]["failed"]) + (0 if A[p]["C3_not_always_empty"] else 1) == fewest]
    chosen = sorted(pool, key=lambda p: (-A[p]["true_total"], A[p]["clean_findings_total"], A[p]["dups_total"], A[p]["prompt_chars"]))[0]

    # ---------------- Development B (uses the chosen prompt's blind validity)
    B = {}
    for m in cands:
        s = sc[m]
        tv = s["targeted_valid"]
        bl = s["blind"][chosen]
        c1 = tv[1] and tv[0] / tv[1] >= 0.95 and bl["n"] and bl["valid"] / bl["n"] >= 0.95
        c2 = s["probe_byte_identical"] is True
        c3 = s["trajectory"] >= 6 and s["E1"] >= 9
        c4 = True
        B[m] = {"root": M.MODELS[m]["root"], "quantization": M.MODELS[m].get("quantization"), "targeted_valid": tv,
                "blind_valid": [bl["valid"], bl["n"]], "E0": s["E0"], "E1": s["E1"], "E2": s["E2"], "trajectory": s["trajectory"],
                "unresolved": s["unresolved"], "invalid_line_refs": s["targeted_invalid_line_refs"], "probe_byte_identical": s["probe_byte_identical"],
                "blind_true_chosen_prompt": bl["true"], "blind_counts_chosen_prompt": bl["counts"],
                "C1_valid": bool(c1), "C2_deterministic": c2, "C3_competence": c3, "C4_resources": c4}
        B[m]["eligible"] = all(B[m][k] for k in ("C1_valid", "C2_deterministic", "C3_competence", "C4_resources"))
    eligB = [m for m in cands if B[m]["eligible"]]
    mem = {"gemma4_12": 24.0, "gemma4_26a4": 17.2, "ministral3_14": 31.5}
    selected = sorted(eligB, key=lambda m: (-B[m]["trajectory"], -(B[m]["E0"] + B[m]["E2"]), B[m]["invalid_line_refs"], mem.get(m, 99)))[0] if eligB else None

    primary = QWEN + ([selected] if selected else [])
    groups = {m: ("weak" if sc[m]["E0"] < 8 else "strong") for m in primary}
    sel = {"dev_plan_sha256": plan_sha, "blind_prompt": chosen, "blind_prompt_sha256": hashlib.sha256(P.BLIND_CANDIDATES[chosen].encode()).hexdigest(),
           "blind_fallback_rule_used": fallback, "eligible_prompts": eligible, "selected_nonqwen": selected,
           "eligible_models": eligB, "infeasible_candidates": infeasible, "capability_groups": groups, "A": A, "B": B}
    (ROOT / "exp2b/dev/selection.json").write_text(json.dumps(sel, indent=1) + "\n")
    (ROOT / "exp2b/dev/capability_groups.json").write_text(json.dumps(groups, indent=1) + "\n")

    # ---------------- reports
    L = ["# Development A — blind-audit prompt bakeoff", "",
         f"Rules pre-registered in `exp2b/dev/DEV_PLAN.md` (sha256 `{plan_sha}`) before any development request. Material: 2A-R2 only "
         "(12 E0 manuscripts from the 2A-R2 matrix subset, two per family, plus the unmodified ELVAE manuscript). Models: "
         f"{', '.join(all_models)}. Scoring: frozen 2A-R2 strict scorer. No 2B manuscript was used.", "",
         "## Candidates", ""]
    for pid in prompts:
        L += [f"### `{pid}` (sha256 `{hashlib.sha256(P.BLIND_CANDIDATES[pid].encode()).hexdigest()}`)", "", "```", P.BLIND_CANDIDATES[pid].split("JSON, with audit_notes")[0].strip(), "```", ""]
    L += ["## Results", "", "| Prompt | Model | Valid | Findings per audit (E0 + clean) | Empty E0 | 5-finding E0 | TRUE (of 12) | PARTIAL | Clean relation FP | Clean findings | Duplicates |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for pid in prompts:
        for m, r in A[pid]["per_model"].items():
            L.append(f"| {pid} | {m} | {r['valid']}/{r['n']} | {r['counts']} | {r['empty_E0']} | {r['max_fill_E0']} | {r['true']} {r['true_cases'] or ''} | {r['partial']} | {r['fp']} | {r['base_findings']} | {r['dups']} |")
    L += ["", "## Rule application", "", "| Prompt | C1 valid | C2 no max-fill | C3 not always empty | C4 clean FP | C5 deterministic | C6 no leak | TRUE total | Clean findings | Duplicates |", "|---|---|---|---|---|---|---|---|---|---|"]
    for pid in prompts:
        a = A[pid]
        L.append(f"| {pid} | {a['C1_valid']} | {a['C2_no_max_fill']} | {a['C3_not_always_empty']} | {a['C4_clean_fp']} | {a['C5_deterministic']} | {a['C6_no_leak']} | {a['true_total']} | {a['clean_findings_total']} | {a['dups_total']} |")
    L += ["", f"Eligible prompts: {eligible or 'none'}." + (" No prompt met every criterion; the pre-registered fallback (fewest failed criteria, then tie-breaks) was applied." if fallback else ""), "",
          f"**Chosen: `{chosen}`** (sha256 `{sel['blind_prompt_sha256']}`). Frozen in `exp2b/protocol.py` as `BLIND_PROMPT_ID`; never retuned on 2B output.", "",
          "## Interpretation (limitation carried into 2B)", "",
          "The pathology that motivated this bakeoff is only partly addressed by prompt wording. The 27B Qwen models return empty findings "
          "lists for almost every audit under all three candidates, while smaller models produce findings. 2B therefore measures blind "
          "discovery under a prompt that permits and does not penalise empty audits; the discovery rate of the strongest verifiers is "
          "bounded by their reluctance to report anything unprompted. The number of candidates was capped at three in advance, and no "
          "further prompt was tried after seeing these results.", ""]
    (ROOT / "exp2b/BLIND_PROMPT_BAKEOFF.md").write_text("\n".join(L) + "\n")

    L = ["# Development B — non-Qwen primary verifier bakeoff", "",
         f"Rules pre-registered in `exp2b/dev/DEV_PLAN.md` (sha256 `{plan_sha}`). Material: 2A-R2 only — targeted neutral trials on the "
         "12 development cases x E0/E1/E2 (36 per model) and the blind audits of Development A. No 2B manuscript was used.", "",
         "## Candidates (fixed before any development request)", "",
         "| Candidate | Model ID | Quantisation | Context | GPUs | Notes |", "|---|---|---|---|---|---|"]
    for m in M.CANDIDATES:
        L.append(f"| {m} | `{M.MODELS[m]['root']}` | {M.MODELS[m].get('quantization')} | 32,768 (max_model_len) | 2,3 (TP2) | "
                 f"{'did not start: infeasible' if m in infeasible else 'served by vLLM 0.23.0, prefix caching off'} |")
    L += ["", "Cached non-Qwen models not considered: gemma-2-9b-it, Llama3-OpenBioLLM-8B, Llama-3-8B-UltraMedical and meditron-7b "
          "(context of at most 8k tokens, below the ~24k-token manuscripts); Mistral-7B-Instruct-v0.2 and Phi-4-mini (older/smaller than "
          "the downloaded candidates of the same families); Llama-3.1-8B (failed as a primary verifier in 2A-R2: trajectory 0%).", "",
          "## Results (development subset; Qwen models shown for reference)", "",
          "| Model | Targeted valid | E0 (of 12) | E1 (of 12) | E2 (of 12) | Trajectory (of 12) | UNRESOLVED | Invalid line refs | Deterministic probes | Blind TRUE (chosen prompt) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for m in all_models:
        s = sc[m]
        L.append(f"| {m} | {s['targeted_valid'][0]}/{s['targeted_valid'][1]} | {s['E0']} | {s['E1']} | {s['E2']} | {s['trajectory']} | {s['unresolved']} | "
                 f"{s['targeted_invalid_line_refs']} | {s['probe_byte_identical']} | {s['blind'][chosen]['true']} |")
    L += ["", "## Rule application", "", "| Candidate | C1 valid | C2 deterministic | C3 competence (traj >= 6, E1 >= 9) | C4 resources | Eligible |", "|---|---|---|---|---|---|"]
    for m in cands:
        b = B[m]
        L.append(f"| {m} | {b['C1_valid']} | {b['C2_deterministic']} | {b['C3_competence']} | {b['C4_resources']} | {b['eligible']} |")
    if selected:
        L += ["", f"**Selected non-Qwen primary verifier: `{selected}` = `{M.MODELS[selected]['root']}`** ({M.MODELS[selected].get('quantization')}), "
              "GPUs 2,3 TP2, port 8102, max_model_len 32768, --no-enable-prefix-caching, chat_template_kwargs "
              f"{M.MODELS[selected].get('chat_template_kwargs')}. Chosen by the pre-registered order (trajectory, then E0+E2, then invalid line "
              "references, then memory) among eligible candidates."]
    else:
        L += ["", "**No candidate met the minimum verifier threshold.** 2B keeps three Qwen primary models; cross-family analysis is "
              "unavailable and any non-Qwen comparison is exploratory only."]
    L += ["", "## Frozen capability grouping for H3", "", "weak verifier = targeted E0 detection < 8 of 12 on this subset under the 2B protocol.", ""]
    L += [f"- {m}: E0 {sc[m]['E0']}/12 -> **{g}**" for m, g in groups.items()]
    L += ["", "Family and capability are confounded wherever the non-Qwen verifier differs in measured competence from the Qwen model it is compared with."]
    (ROOT / "exp2b/MODEL_BAKEOFF.md").write_text("\n".join(L) + "\n")
    print(json.dumps({k: sel[k] for k in ("blind_prompt", "blind_fallback_rule_used", "eligible_prompts", "selected_nonqwen", "eligible_models", "capability_groups")}, indent=1))


if __name__ == "__main__":
    main()
