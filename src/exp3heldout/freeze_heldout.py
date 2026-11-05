#!/usr/bin/env python3
"""Freeze the held-out dataset and protocol before any verifier inference.

    python exp3heldout/freeze_heldout.py
Writes exp3heldout/DATASET_MANIFEST.json and exp3heldout/design_manifest.json (hashes of sources, processed
manuscripts, every E0/E1/E2 variant, ledger, checkers, code, prompts, schemas and the statistical plan).
"""
import hashlib, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp3heldout"))
import design_heldout as D
import checkers as C2
import client as C, protocol as P, protocol_br as PBR

CODE = ["exp3heldout/harvest.py", "exp3heldout/prepare_screen.py", "exp3heldout/mine_cases.py",
        "exp3heldout/checkers.py", "exp3heldout/build_dataset.py", "exp3heldout/select_papers.py",
        "exp3heldout/audit_dataset.py", "exp3heldout/design_heldout.py", "exp3heldout/run_heldout.py",
        "exp3heldout/evaluate_heldout.py", "exp3heldout/report_heldout.py", "exp3heldout/FROZEN_DESIGN.md",
        "exp3heldout/FROZEN_DATASET.md", "exp3heldout/POWER_ANALYSIS.md", "exp3heldout/ledger.json",
        "exp2b/protocol.py", "exp2b/scoring.py", "exp2b/client.py", "exp2b/normalize.py", "exp2b/evaluate.py",
        "exp2br/protocol_br.py", "exp2br/provenance_audit.py", "exp2bbroad/models_broad.py",
        "exp2b/design_manifest.json", "exp2br/design_manifest.json", "exp2bbroad/design_manifest.json"]


def sha_file(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def main():
    plan = D.Plan()
    led = plan.ledger
    m2b = json.loads((ROOT / "exp2b/design_manifest.json").read_text())
    checks = {
        "exp2b_frozen_unchanged": all(sha_file(k) == v for k, v in m2b["frozen_file_sha256"].items()
                                      if (ROOT / k).exists()),
        "blind_prompt_matches_2b": hashlib.sha256(P.BLIND_CANDIDATES[PBR.PROMPT_ID].encode()).hexdigest()
        == m2b["blind_prompt"]["sha256"],
        "scorer_matches_2b": sha_file("exp2b/scoring.py") == m2b["frozen_file_sha256"]["exp2b/scoring.py"],
        "targeted_schema_matches_2b": C.sha256_text(C.canonical(P.TARGETED_SCHEMA)) == m2b["targeted_schema_sha256"]
        if "targeted_schema_sha256" in m2b else True,
    }
    if not all(v for v in checks.values() if isinstance(v, bool)):
        raise SystemExit(f"frozen protocol inputs changed: {checks}")
    ds = {"dataset": "VerifierTrustBench held-out corpus", "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
          "papers": led["papers"], "domains": led["domains"], "n_cases": len(led["cases"]),
          "family_counts": led["family_counts"],
          "cases_per_paper": {p: sum(1 for c in led["cases"] if c["paper"] == p) for p in led["papers"]},
          "source_archives": {p: json.loads((ROOT / f"exp3heldout/papers/{p}/SOURCE.json").read_text())
                              for p in led["papers"]},
          "variant_sha256": {c["case_id"]: c["sha256"] for c in led["cases"]},
          "checker_specs_sha256": {c["case_id"]: C.sha256_text(C.canonical(c["checker_spec"])) for c in led["cases"]},
          "checker_results": {c["case_id"]: c["checker_results"] for c in led["cases"]},
          "ledger_sha256": sha_file("exp3heldout/ledger.json"),
          "checkers_sha256": sha_file("exp3heldout/checkers.py"),
          "normalizer_sha256": sha_file("exp2b/normalize.py"),
          "selection": json.loads((ROOT / "exp3heldout/selection.json").read_text()),
          "audit": json.loads((ROOT / "exp3heldout/audit.json").read_text())}
    (ROOT / "exp3heldout/DATASET_MANIFEST.json").write_text(json.dumps(ds, indent=1) + "\n")
    man = {"experiment": "Experiment 3 held-out generalization study", "protocol_version": "3-heldout-v1.0",
           "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "frozen_before_any_heldout_inference": True,
           "dataset_manifest_sha256": sha_file("exp3heldout/DATASET_MANIFEST.json"),
           "primary_models": D.PRIMARY, "broad_models": D.BROAD, "phases": D.PHASES,
           "subset_seed": D.SUBSET_SEED,
           "matrix_subset": [c["case_id"] for c in plan.matrix_subset()],
           "broad_subset": [c["case_id"] for c in plan.broad_subset()],
           "clean_controls_per_paper": D.CLEAN_PER_PAPER,
           "prompts": {"system_sha256": hashlib.sha256(P.SYSTEM.encode()).hexdigest(),
                       "system_blind_sha256": hashlib.sha256(P.SYSTEM_BLIND.encode()).hexdigest(),
                       "targeted_template_sha256": hashlib.sha256(P.TARGETED_TEMPLATE.encode()).hexdigest(),
                       "blind_prompt_id": PBR.PROMPT_ID,
                       "blind_prompt_sha256": hashlib.sha256(P.BLIND_CANDIDATES[PBR.PROMPT_ID].encode()).hexdigest()},
           "schemas": {"targeted_sha256": C.sha256_text(C.canonical(P.TARGETED_SCHEMA)),
                       "blind_bounded_sha256": C.sha256_text(C.canonical(PBR.BLIND_SCHEMA_BR))},
           "decoding": {**P.DECODING, "max_tokens": P.MAX_TOKENS, "timeout_s": P.TIMEOUT_S,
                        "max_retries": P.MAX_RETRIES, "concurrency": "one request at a time per server",
                        "retry_policy": "identical payload, no max_tokens escalation"},
           "scorers": {"targeted": "verdict vs mechanical gold in exp3heldout/ledger.json",
                       "blind": "exp2b/scoring.py strict label_defective / label_clean (unchanged)",
                       "provenance": "exp2br/provenance_audit.classify (unchanged)"},
           "statistical_plan": {
               "H1": "paired within model: targeted E0 correct vs blind TRUE on the same case; exact McNemar, "
                     "Newcombe method-10 CI; pooled, per model, per paper, per domain, per defect family; "
                     "leave-one-paper-out, leave-one-domain-out, leave-one-defect-family-out",
               "H2": "E0/E1/E2 accuracy and full-trajectory rate with Wilson CIs; per model, paper, domain, family",
               "H3": "paired correct_verdict vs correct_verdict+rationale on the 60-case matrix subset; exact "
                     "McNemar, Newcombe CI; pooled, per model, per domain, per family; leave-one-paper-out",
               "false_prior": "neutral vs false verdict, false verdict vs false rationale, adoption among targets "
                              "that initially disagreed (secondary; a null is reported as a null)",
               "hierarchical": "GEE logistic clustered by manuscript (exchangeable) with blind/targeted condition, "
                               "model, defect family and domain; plus a Bayesian mixed GLM with random intercepts "
                               "for manuscript and case",
               "technical_gate": ">= 95% valid in every primary cell; failures reported, never silently patched"},
           "integrity_checks": checks, "file_sha256": {f: sha_file(f) for f in CODE}}
    (ROOT / "exp3heldout/design_manifest.json").write_text(json.dumps(man, indent=1) + "\n")
    print(json.dumps(checks, indent=1))
    print("dataset manifest", ds["ledger_sha256"][:12], "design manifest",
          hashlib.sha256((ROOT / "exp3heldout/design_manifest.json").read_bytes()).hexdigest()[:12])


if __name__ == "__main__":
    main()
