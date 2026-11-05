#!/usr/bin/env python3
"""Freeze the Experiment 2B design before any 2B manuscript inference.

    python exp2b/freeze.py --label v1.0

Writes exp2b/design_manifest.json and exp2b/FROZEN_DESIGN.md. The runner refuses to start if any hashed file changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "exp2b"
sys.path.insert(0, str(EXP))
import decision_rules as DR  # noqa: E402
import design as D  # noqa: E402
import models as M  # noqa: E402
import protocol as P  # noqa: E402
import scoring as S  # noqa: E402

FROZEN = ["exp2b/client.py", "exp2b/protocol.py", "exp2b/scoring.py", "exp2b/normalize.py", "exp2b/design.py",
          "exp2b/models.py", "exp2b/run_exp2b.py", "exp2b/evaluate.py", "exp2b/decision_rules.py", "exp2b/orchestrate.sh",
          "exp2b/run_sequence.sh", "exp2b/build_benchmark.py", "exp2b/cases/common.py", "exp2b/ledger.json",
          "exp2b/dev/capability_groups.json", "exp2ar2/ledger.json"]
INFORMATIONAL = ["exp2b/freeze.py", "exp2b/determinism_probe.py", "exp2b/context_gate.py", "exp2b/CONTEXT_GATE.json",
                 "exp2b/CASE_AUDIT.md", "exp2b/case_audit.csv", "exp2b/PAPER_SELECTION.md", "exp2b/BLIND_PROMPT_BAKEOFF.md",
                 "exp2b/MODEL_BAKEOFF.md", "exp2b/dev/DEV_PLAN.md", "exp2b/dev/results/scores.json",
                 "exp2b/papers/screen_arxiv.py", "exp2b/papers/screen_stage1.jsonl", "exp2b/papers/screen_stage2.jsonl",
                 "exp2b/papers/STAGE2_CRITERIA.md", "exp2b/papers/prepare.py", "exp2b/dev/bakeoff.py"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def power_exact(n_disc: float, alpha=0.05, target=0.8):
    """Smallest harmful share of discordant pairs detectable with exact two-sided binomial test at the expected
    discordant count (rounded), 80% power. Returns (share, net_effect_per_block)."""
    d = max(1, int(round(n_disc)))

    def pval(k):
        k2 = min(k, d - k)
        return min(1.0, 2 * sum(math.comb(d, i) for i in range(k2 + 1)) / 2 ** d)
    reject = [k for k in range(d + 1) if pval(k) < alpha and k > d / 2]
    for pi in [x / 100 for x in range(50, 101)]:
        power = sum(math.comb(d, k) * pi ** k * (1 - pi) ** (d - k) for k in reject)
        if power >= target:
            return pi, d
    return None, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    a = ap.parse_args()
    if P.BLIND_PROMPT_ID is None:
        raise SystemExit("blind prompt not selected")
    ledger = json.loads((EXP / "ledger.json").read_text())
    plan_full, plan_val = D.Plan("full"), D.Plan("validation")
    frozen = {rel: sha(ROOT / rel) for rel in FROZEN}
    frozen.update({f"exp2b/cases/{p.name}": sha(p) for p in sorted((EXP / "cases").glob("p2*.py"))})
    bench = {}
    for c in ledger["cases"]:
        for st in ("E0", "E1", "E2"):
            bench[c["paths"][st]] = sha(ROOT / c["paths"][st])
    for p in ledger["papers"]:
        bench[f"exp2b/papers/{p['paper']}/SOURCE.json"] = sha(EXP / "papers" / p["paper"] / "SOURCE.json")
    for cid in D.ANCHOR_CASES:
        c = plan_full.r2_by_id[cid]
        for st in ("E0", "E1", "E2"):
            bench[c["paths"][st]] = sha(ROOT / c["paths"][st])
    counts_full, counts_val = plan_full.counts(), plan_val.counts()
    n_blocks = len(plan_full.matrix_cases()) * 2 * len(D.PRIMARY)
    # R2 discordance rates (runs/exp2ar2_20260913_123732 REPORT.md): false_verdict vs neutral 10/96, false_rationale vs
    # neutral 19/95, correct_rationale vs correct_verdict 22/96.
    power = {}
    for name, rate in (("false_verdict_vs_neutral", 10 / 96), ("false_rationale_vs_neutral", 19 / 95),
                       ("correct_rationale_vs_correct_verdict", 22 / 96)):
        share, d = power_exact(rate * n_blocks)
        power[name] = {"r2_discordant_rate": round(rate, 4), "blocks": n_blocks, "expected_discordant": d,
                       "min_detectable_share_of_discordants_80pct_power": share,
                       "min_detectable_net_accuracy_change": round((2 * share - 1) * d / n_blocks, 4) if share else None,
                       "approx_null_ci_halfwidth": round(1.96 * math.sqrt(d) / n_blocks, 4)}
    manifest = {
        "experiment": "Experiment 2B cross-manuscript generalization", "freeze_label": a.label,
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "frozen_before_2b_inference": True,
        "protocol_version": P.PROTOCOL_VERSION, "predecessor": "runs/exp2ar2_20260913_123732 (FINAL, GO_TO_2B)",
        "primary_models": {m: M.MODELS[m] for m in D.PRIMARY}, "selected_nonqwen": D.NONQWEN,
        "phases": D.PHASE_MODELS, "pairs": D.PAIRS, "papers": [p["paper"] for p in ledger["papers"]],
        "paper_sources": {p["paper"]: p["source"] for p in ledger["papers"]},
        "family_counts": ledger["family_counts"], "matrix_cases": [c["case_id"] for c in plan_full.matrix_cases()],
        "anchor_cases": D.ANCHOR_CASES, "validation_scope": D.VALIDATION,
        "blind_prompt": {"id": P.BLIND_PROMPT_ID, "sha256": hashlib.sha256(P.BLIND_CANDIDATES[P.BLIND_PROMPT_ID].encode()).hexdigest()},
        "prompts_sha256": {"system": hashlib.sha256(P.SYSTEM.encode()).hexdigest(), "system_blind": hashlib.sha256(P.SYSTEM_BLIND.encode()).hexdigest(),
                           "targeted_template": hashlib.sha256(P.TARGETED_TEMPLATE.encode()).hexdigest()},
        "decoding": {**P.DECODING, "response_format": P.RESPONSE_FORMAT, "max_tokens": P.MAX_TOKENS, "max_retries": P.MAX_RETRIES,
                     "retry_policy": "identical payload; no budget escalation", "timeout_s": P.TIMEOUT_S,
                     "chat_template_kwargs": {m: M.MODELS[m].get("chat_template_kwargs") for m in D.PRIMARY}},
        "context": {"max_model_len": 32768, "gate": "exp2b/CONTEXT_GATE.json"},
        "seed_rule": "seed_for(case_id, state); blind E0 seed_for(case_id,'blind'); clean control seed_for(paper+'::clean','blind'); anchor seed_for('anchor::'+case,state)",
        "trial_counts_full": counts_full, "trial_counts_full_total": sum(counts_full.values()),
        "trial_counts_validation": counts_val, "power_plan_secondary": power,
        "statistics": {"paired": "exact two-sided McNemar (binomial on discordant pairs); Newcombe method-10 95% CI for paired differences",
                       "rates": "Wilson 95% CI", "direction": "exact sign test", "estimability": [S.ESTIMABLE_MIN_N, S.ESTIMABLE_MIN_CASES]},
        "decision_rules": DR.__doc__, "deviations_from_2ar2": P.DEVIATIONS_FROM_2AR2,
        "frozen_file_sha256": frozen, "benchmark_file_sha256": bench,
        "informational_sha256": {rel: sha(ROOT / rel) for rel in INFORMATIONAL if (ROOT / rel).exists()},
    }
    out = EXP / "design_manifest.json"
    out.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    msha = sha(out)
    L = ["# Experiment 2B — Frozen Design", "", f"Freeze label `{a.label}`, frozen {manifest['frozen_at']}, before any 2B manuscript inference.  ",
         f"`design_manifest.json` sha256: `{msha}`", "",
         "Once the first 2B manuscript request is sent the scientific design is frozen. A critical defect found later is "
         "handled by stopping, documenting, versioning the design and using a new run directory.", "",
         "## Scientific question", "",
         "Do the discovery-confirmation gap, evidence responsiveness, and rationale-mediated information transfer generalise "
         "across independent scientific manuscripts? Agreement alone is never called independent corroboration; the analysis "
         "distinguishes agreement, targeted confirmation, independent discovery and evidence-responsive verification.", "",
         "## Primary hypotheses", "",
         "- **H1 cross-manuscript discovery-confirmation gap.** Unit: native edited case x model. Paired: strict blind TRUE_DETECTION "
         "of the E0 defect vs targeted neutral ISSUE_PRESENT on the same E0 manuscript. Pooled over the five new papers, per model, "
         "per paper, per family, leave-one-paper-out, leave-one-family-out. Exact McNemar; Newcombe CI.",
         "- **H2 cross-manuscript evidence responsiveness.** E0 detection, E1 clearance, E2 detection and full E0/E1/E2 trajectory, "
         "with failure patterns (always-issue, always-no-issue, detects-but-fails-to-clear, clears-but-misses-E2, unresolved, misses-E0).",
         "- **H3 correct-rationale information transfer.** Matched blocks: correct verdict vs the same correct verdict plus an "
         "evidence-grounded rationale; helpful/harmful/unchanged, exact McNemar, accuracy difference with CI; per model, paper, family, "
         "LOPO, LOFO; strong vs weak verifiers as frozen by the development bakeoff (`exp2b/dev/capability_groups.json`).",
         "", "## Secondary (pre-registered)", "",
         "- **S1 false-prior contamination:** neutral vs false verdict; false verdict vs false verdict + plausible false rationale; "
         "harmful flips, recoveries, adoption among blocks whose neutral answer disagreed with the prior; CIs; exact tests. A null is "
         "reported with its detectable-effect bound, never as 'no effect'.",
         "", "Power plan (expected discordant blocks from 2A-R2 rates; exact two-sided test, 80% power):", "",
         "| Comparison | 2A-R2 discordant rate | Blocks | Expected discordant | Min detectable harmful share | Min detectable net change | Approx. null 95% CI half-width |",
         "|---|---|---|---|---|---|---|"]
    for k, v in power.items():
        L.append(f"| {k} | {v['r2_discordant_rate']} | {v['blocks']} | {v['expected_discordant']} | {v['min_detectable_share_of_discordants_80pct_power']} | "
                 f"{v['min_detectable_net_accuracy_change']} | ±{v['approx_null_ci_halfwidth']} |")
    L += ["", "## Exploratory (never promoted)", "", "- actual naturally wrong peer + rationale; same-model / same-family / cross-family influence; "
          "capability x rationale benefit; defect-family heterogeneity; manuscript heterogeneity.", "",
          "## Development choices (made on 2A-R2 material only)", "",
          f"- Blind prompt: `{P.BLIND_PROMPT_ID}` (sha256 `{manifest['blind_prompt']['sha256']}`), see `BLIND_PROMPT_BAKEOFF.md`.",
          f"- Non-Qwen primary verifier: `{D.NONQWEN}` ({M.MODELS[D.NONQWEN]['root'] if D.NONQWEN else 'none'}), see `MODEL_BAKEOFF.md`.",
          f"- Capability groups: {json.dumps(json.loads((EXP / 'dev/capability_groups.json').read_text()))}.", "",
          "## Benchmark", "", f"- Papers: {', '.join(manifest['papers'])} (selection: `PAPER_SELECTION.md`); ELVAE is anchor-only.",
          f"- {len(ledger['cases'])} native-edit cases; family counts {ledger['family_counts']}; every case has a deterministic checker "
          "that the builder requires to return inconsistent/consistent/inconsistent on E0/E1/E2 (`CASE_AUDIT.md`).",
          f"- Matrix subset (4 per paper): {', '.join(manifest['matrix_cases'])}.",
          f"- ANCHOR_REPLICATION: {', '.join(D.ANCHOR_CASES)} (2A-R2 cases not used in development).", "",
          "## Trial plan", "", "| Component | Full | Validation |", "|---|---:|---:|"]
    for k in counts_full:
        L.append(f"| {k} | {counts_full[k]} | {counts_val[k]} |")
    L += [f"| **total** | **{sum(counts_full.values())}** | **{sum(counts_val.values())}** |", "",
          "Blind clean controls: one audit of each unmodified paper per model, scored against all 12 relations of that paper. A second "
          "audit of the same request would be byte-identical under the deterministic serving verified by the gate, so it adds no information.",
          "", "Pairs (source -> target, category):", ""]
    for ph, pl in D.PAIRS.items():
        for s_, t_, c_ in pl:
            L.append(f"- {ph}: {s_} -> {t_} ({c_}); 20 matrix cases x E0/E1 x (verdict, verdict+rationale), neutral twin = target's evidence trial")
    L += ["", "## Instrument", "", "- Models, endpoints, quantisation and chat-template kwargs: `design_manifest.json` primary_models.",
          "- temperature 0; JSON-schema guided decoding (line IDs <= 6 matching L00000, <= 5 findings, verdict unconstrained); "
          f"max_tokens targeted {P.MAX_TOKENS['targeted']}, blind {P.MAX_TOKENS['blind']}; <= {P.MAX_RETRIES} identical retries; "
          "prefix caching off on non-hybrid servers; one request at a time per server.",
          "- Provenance per trial: EXACT / ADJACENT_BLANK / NONEXISTENT line IDs; target support SUPPORTED / SUPPORTED_ADJACENT / "
          "UNSUPPORTED. Verdict validity and provenance validity are separate metrics; invalid provenance never invalidates a verdict.",
          "- Strict blind scorer (unchanged from 2A-R2): TRUE_DETECTION needs an exact target line, a contradiction token and family "
          "vocabulary in the allegation; sensitivity (allegation+summary) and adjacent-line variants reported, never substituted.",
          "", "## Decision criteria", "", "```", DR.__doc__.strip(), "```", "", "## Frozen file hashes", ""]
    L += [f"- `{k}`: `{v}`" for k, v in frozen.items()]
    L += [f"- {len(bench)} benchmark/source files hashed in `design_manifest.json`", ""]
    (EXP / "FROZEN_DESIGN.md").write_text("\n".join(L) + "\n")
    print(f"FROZEN {a.label}: {msha}")
    print(json.dumps(counts_full), sum(counts_full.values()))
    print(json.dumps(power, indent=1))


if __name__ == "__main__":
    main()
