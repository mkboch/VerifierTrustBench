#!/usr/bin/env python3
"""Freeze Experiment 2B-broad before any scientific inference.   python exp2bbroad/freeze_broad.py"""
import hashlib, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2bbroad"))
import models_broad as MB
sys.path.insert(0, str(ROOT / "exp2br"))
import client as C, design as D, protocol as P, protocol_br as PBR

FILES = ["exp2bbroad/models_broad.py", "exp2bbroad/run_broad.py", "exp2bbroad/preflight_broad.py", "exp2bbroad/evaluate_broad.py",
         "exp2bbroad/serve_broad.sh", "exp2bbroad/drive.sh", "exp2bbroad/FROZEN_DESIGN.md",
         "exp2b/protocol.py", "exp2b/scoring.py", "exp2b/client.py", "exp2b/design.py", "exp2b/models.py", "exp2b/normalize.py",
         "exp2b/evaluate.py", "exp2b/ledger.json", "exp2b/design_manifest.json",
         "exp2br/protocol_br.py", "exp2br/provenance_audit.py", "exp2br/design_manifest.json",
         "runs/exp2b_20260914_142911/evidence_trials.jsonl", "runs/exp2b_20260914_142911/matrix_trials.jsonl",
         "runs/exp2br_20260914_214259/blind_trials.jsonl"]


def sha(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def main():
    m2b = json.loads((ROOT / "exp2b/design_manifest.json").read_text())
    m2br = json.loads((ROOT / "exp2br/design_manifest.json").read_text())
    checks = {
        "exp2b_frozen_unchanged": all(sha(k) == v for k, v in m2b["frozen_file_sha256"].items() if (ROOT / k).exists()),
        "exp2b_benchmark_unchanged": all(sha(k) == v for k, v in m2b["benchmark_file_sha256"].items() if (ROOT / k).exists()),
        "exp2br_reused_unchanged": all(sha(k) == v for k, v in m2br["reused_2b_file_sha256"].items() if (ROOT / k).exists()),
        "blind_prompt_sha256": hashlib.sha256(P.BLIND_CANDIDATES[PBR.PROMPT_ID].encode()).hexdigest(),
        "blind_prompt_matches_2b": hashlib.sha256(P.BLIND_CANDIDATES[PBR.PROMPT_ID].encode()).hexdigest() == m2b["blind_prompt"]["sha256"],
        "scorer_matches_2b": sha("exp2b/scoring.py") == m2b["frozen_file_sha256"]["exp2b/scoring.py"],
    }
    if not all(v for k, v in checks.items() if isinstance(v, bool)):
        raise SystemExit(f"frozen inputs changed: {checks}")
    plan = D.Plan("full")
    man = {
        "experiment": "Experiment 2B-broad (broad-family characterization)", "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "frozen_before_any_scientific_inference": True, "protocol_version": "2B-broad-v1.0",
        "relationship_to_2B_family": "Eligibility decision of runs/exp2bfamily_20260915_152058 (REVISE_FAMILY_EXTENSION) is untouched;"
                                     " this experiment characterizes technically viable models and never reclassifies them as primary.",
        "models": {m: {k: v for k, v in MB.MODELS[m].items() if k not in ("endpoint",)} for m in MB.ALL_MODELS},
        "competence_class": MB.COMPETENCE_CLASS, "run_here": MB.RUN_HERE,
        "reused_records": {"evidence_matrix": "runs/exp2b_20260914_142911", "blind": "runs/exp2br_20260914_214259"},
        "excluded_checkpoints": MB.EXCLUDED,
        "benchmark": {"papers": sorted({c["paper"] for c in plan.cases()}), "cases": len(plan.cases()),
                      "matrix_cases": len(plan.matrix_cases()), "blind_items": len(plan.blind_items()),
                      "ledger_sha256": sha("exp2b/ledger.json")},
        "prompts": {"system_sha256": hashlib.sha256(P.SYSTEM.encode()).hexdigest(),
                    "system_blind_sha256": hashlib.sha256(P.SYSTEM_BLIND.encode()).hexdigest(),
                    "targeted_template_sha256": hashlib.sha256(P.TARGETED_TEMPLATE.encode()).hexdigest(),
                    "blind_prompt_id": PBR.PROMPT_ID, "blind_prompt_sha256": checks["blind_prompt_sha256"]},
        "schemas": {"targeted_sha256": C.sha256_text(C.canonical(P.TARGETED_SCHEMA)),
                    "blind_bounded_sha256": C.sha256_text(C.canonical(PBR.BLIND_SCHEMA_BR))},
        "decoding": {**P.DECODING, "max_tokens": P.MAX_TOKENS, "timeout_s": P.TIMEOUT_S, "max_retries": P.MAX_RETRIES,
                     "retry_policy": "identical payload, no max_tokens escalation", "concurrency": "one request at a time per server",
                     "single_run_protocol": "each planned request is issued once; retries only on failure status"},
        "scorer": {"targeted": "verdict vs frozen gold in exp2b/ledger.json",
                   "blind": "exp2b/scoring.py strict blind scorer (label_defective / label_clean), sha256 " + sha("exp2b/scoring.py"),
                   "provenance": "exp2br/provenance_audit.classify"},
        "statistical_plan": {
            "per_model": ["E0/E1/E2 detection and clearance with Wilson CIs", "full E0-E1-E2 trajectory rate",
                          "UNRESOLVED and failure rates", "blind TRUE/PARTIAL/MISSED, clean false positives, zero-finding rate",
                          "H1 paired targeted-E0 vs blind-E0 (exact McNemar, Newcombe CI)",
                          "H3 paired correct_verdict vs correct_rationale", "false-prior: neutral vs false_verdict and"
                          " false_verdict vs false_rationale", "provenance classes", "error taxonomy shares"],
            "aggregation": ["by family", "by competence_class (primary vs characterization)", "by parameter scale (descriptive)",
                            "by reasoning_mode (direct vs native_reasoning; never pooled silently)"],
            "qualitative_H1_criterion": "within-model targeted-only > blind-only with exact McNemar p < 0.05",
            "no_causal_claims": "family, scale and reasoning-mode contrasts are observational and reported descriptively"},
        "file_sha256": {f: sha(f) for f in FILES},
        "integrity_checks": checks,
    }
    (ROOT / "exp2bbroad/design_manifest.json").write_text(json.dumps(man, indent=1) + "\n")
    print(json.dumps(checks, indent=1))
    print("manifest sha256", hashlib.sha256((ROOT / "exp2bbroad/design_manifest.json").read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
