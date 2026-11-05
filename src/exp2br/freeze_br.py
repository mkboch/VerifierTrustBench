#!/usr/bin/env python3
"""Freeze Experiment 2B-R before any repaired blind inference.   python exp2br/freeze_br.py --label v1.0"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2br"))
import protocol_br as PB  # noqa: E402
import run_exp2br as RB  # noqa: E402
import evaluate_br as EB  # noqa: E402
import client as C  # noqa: E402
import design as D  # noqa: E402
import models as M  # noqa: E402
import protocol as P  # noqa: E402

FROZEN = ["exp2br/protocol_br.py", "exp2br/run_exp2br.py", "exp2br/evaluate_br.py", "exp2br/determinism_probe_br.py",
          "exp2br/run_sequence_br.sh"]
REUSED = ["exp2b/protocol.py", "exp2b/scoring.py", "exp2b/client.py", "exp2b/design.py", "exp2b/models.py", "exp2b/normalize.py",
          "exp2b/evaluate.py", "exp2b/orchestrate.sh", "exp2b/ledger.json", "exp2b/dev/capability_groups.json", "exp2b/design_manifest.json",
          "runs/exp2b_20260914_142911/evidence_trials.jsonl", "runs/exp2b_20260914_142911/blind_trials.jsonl",
          "runs/exp2b_20260914_142911/decision.json", "runs/exp2b_20260914_142911/RUN_META.json"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    a = ap.parse_args()
    man2b = json.loads((ROOT / "exp2b/design_manifest.json").read_text())
    # scorer and prompt identical to the 2B freeze
    assert sha(ROOT / "exp2b/scoring.py") == man2b["frozen_file_sha256"]["exp2b/scoring.py"], "scorer differs from 2B"
    assert sha(ROOT / "exp2b/evaluate.py") == man2b["frozen_file_sha256"]["exp2b/evaluate.py"], "2B evaluator differs"
    b1 = hashlib.sha256(P.BLIND_CANDIDATES[PB.PROMPT_ID].encode()).hexdigest()
    assert b1 == man2b["blind_prompt"]["sha256"], "B1 prompt differs from 2B"
    items = RB.items("full")
    reused = {r: sha(ROOT / r) for r in REUSED}
    for it in items:
        rel = f"exp2b/papers/{it['paper']}/E1.tex" if it["kind"] == "clean" else next(c for c in D.Plan("full").all_cases if c["case_id"] == it["case_id"])["paths"]["E0"]
        reused[rel] = sha(ROOT / rel)
    manifest = {
        "experiment": "Experiment 2B-R blind-audit integrity repair", "freeze_label": a.label, "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "frozen_before_repaired_blind_inference": True, "protocol_version": PB.PROTOCOL_VERSION,
        "statement": "The scientific blind prompt and scorer are unchanged; only bounded structured-output constraints were changed for technical reliability.",
        "blind_prompt": {"id": PB.PROMPT_ID, "sha256": b1, "identical_to_2B": True},
        "system_blind_sha256": hashlib.sha256(P.SYSTEM_BLIND.encode()).hexdigest(),
        "scorer": {"file": "exp2b/scoring.py", "sha256": reused["exp2b/scoring.py"], "identical_to_2B": True},
        "blind_schema_2b_sha256": C.sha256_text(C.canonical(P.BLIND_SCHEMA)),
        "blind_schema_2br_sha256": C.sha256_text(C.canonical(PB.BLIND_SCHEMA_BR)), "blind_schema_2br": PB.BLIND_SCHEMA_BR,
        "schema_change": PB.SCHEMA_DIFF, "bounds_rationale": PB.__doc__,
        "models": {m: M.MODELS[m] for m in D.PRIMARY}, "phases": D.PHASE_MODELS,
        "decoding": {**P.DECODING, "max_tokens_blind": P.MAX_TOKENS["blind"], "timeout_s": P.TIMEOUT_S["blind"],
                     "max_retries": P.MAX_RETRIES, "retry_policy": "identical payload; no max_tokens escalation"},
        "seeds": "unchanged from 2B: defective seed_for(case_id,'blind'); clean seed_for(paper+'::clean','blind')",
        "plan_full": {"audits_per_model": len(items), "models": len(D.PRIMARY), "total": len(items) * len(D.PRIMARY),
                      "defective": sum(it["kind"] == "defective" for it in items), "clean": sum(it["kind"] == "clean" for it in items)},
        "plan_validation": {"ids": RB.VALIDATION_IDS, "total": len(RB.VALIDATION_IDS) * len(D.PRIMARY)},
        "reused_from_2b_not_rerun": ["targeted-neutral E0 verdicts (H1 pairing)", "evidence trajectories (H2)", "controlled matrix (H3, S1)",
                                     "actual pairs", "ELVAE anchor", "targeted-text leakage"],
        "decision_rules": EB.__doc__,
        "frozen_file_sha256": {r: sha(ROOT / r) for r in FROZEN}, "reused_2b_file_sha256": reused,
        "informational_sha256": {r: sha(ROOT / r) for r in ["exp2br/freeze_br.py", "exp2br/INITIAL_STATE.md", "exp2br/smoke/schema_support.py",
                                                            "exp2br/smoke/schema_support_large.json"]},
    }
    out = ROOT / "exp2br/design_manifest.json"
    out.write_text(json.dumps(manifest, indent=1) + "\n")
    msha = sha(out)
    L = ["# Experiment 2B-R — Frozen Design", "", f"Label `{a.label}`, frozen {manifest['frozen_at']}, before any repaired blind inference.  ",
         f"`design_manifest.json` sha256 `{msha}`", "",
         f"**{manifest['statement']}**", "",
         "## Purpose", "", "Only: can the blind-audit component be executed reliably under a minimally constrained output schema without changing the "
         "scientific blind-review task? No new hypothesis. Evidence, matrix, pair and anchor experiments are not rerun; their immutable 2B "
         "results are reused.", "",
         "## Failure audit that motivates the change", "",
         "All five 2B blind truncations were inside `audit_notes` (never reaching `findings`): qwen36_27 by exhaustive non-repeating enumeration "
         "of checks, gemma4_12 by a repetitive loop. The 2B schema bounded list lengths only (`exp2br/INITIAL_STATE.md`).", "",
         "## Exact schema change (the only change)", "", "```json", json.dumps(PB.SCHEMA_DIFF, indent=1), "```", "",
         "Bounds follow the frozen B1 prompt's own instructions (audit_notes under 300 words, evidence_summary under 50, allegation under 40) at "
         "8 characters per word; category is a short label (80). They were chosen from the prompt semantics, not from any result, and are "
         "applied to every model and manuscript. Maximum possible output is about 7,000 characters, far below the unchanged 4,096-token budget, "
         "so a bounded audit cannot truncate. The installed vLLM 0.23.0 guided decoding enforces maxLength, maxItems, enum and integer ranges "
         "(`smoke/schema_support_large.json`). All other schema elements, the B1 prompt, the blind system prompt, seeds, temperature, "
         "max_tokens, chat-template kwargs, servers and the scorer are byte-identical to 2B; `protocol_br._self_check` asserts the schema "
         "differs only by the four maxLength keys.", "",
         f"- B1 prompt sha256 `{b1}` (= 2B)", f"- 2B blind schema sha256 `{manifest['blind_schema_2b_sha256']}` -> 2B-R `{manifest['blind_schema_2br_sha256']}`",
         f"- Scorer `exp2b/scoring.py` sha256 `{reused['exp2b/scoring.py']}` (= 2B)", "",
         "## Plan", "", f"- Full: all {len(items)} frozen 2B blind items (60 defective E0 manuscripts, 5 clean papers) x 4 models = {len(items) * 4} audits; "
         "no mixing with 2B blind outputs.", f"- Validation: {', '.join(RB.VALIDATION_IDS)} x 4 models = {len(RB.VALIDATION_IDS) * 4}, plus 2 requests x 3 repeats per model "
         "determinism probes; acceptance 100% valid, 0 truncation/parse/schema failures, byte-identical repeats, 0 request-hash mismatches.",
         "- H1 recomputed with 2B-R blind audits paired with the immutable 2B targeted-neutral E0 verdicts; original 2B blind results reported as a sensitivity comparison.", "",
         "## Decision rules", "", "```", EB.__doc__.strip(), "```", "",
         "## Frozen file hashes", ""] + [f"- `{k}`: `{v}`" for k, v in manifest["frozen_file_sha256"].items()] + \
        [f"- reused 2B files and manuscripts: {len(reused)} hashed in `design_manifest.json`", ""]
    (ROOT / "exp2br/FROZEN_DESIGN.md").write_text("\n".join(L) + "\n")
    print("FROZEN", a.label, msha)


if __name__ == "__main__":
    main()
