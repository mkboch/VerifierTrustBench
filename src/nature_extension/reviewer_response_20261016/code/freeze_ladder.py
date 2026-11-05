#!/usr/bin/env python3
"""B4: freeze the localization-ladder design BEFORE the first new request."""
from __future__ import annotations
import csv, hashlib, json, sys, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OUT / "code"))
for p in ("exp3heldout", "exp2b", "exp2br", "exp2bbroad"):
    sys.path.insert(0, str(ROOT / p))

import design_heldout as D      # noqa: E402
import protocol as P            # noqa: E402
import protocol_br as PBR       # noqa: E402
import models_broad as MB       # noqa: E402
import ladder_protocol as LP    # noqa: E402
from client import canonical, sha256_text  # noqa: E402

MODELS = ["qwen38_27", "qwen36_27", "gemma4_12", "granite42_30", "qwen3_8"]


def sha_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main() -> int:
    LP.self_check()
    plan = D.Plan()
    cases = {c["case_id"]: c for c in plan.cases}
    subset = sorted({r["case_id"] for r in csv.DictReader(
        (OUT / "data/PROFILE_12SYSTEM_ITEMLEVEL.csv").open())})
    assert len(subset) == 60

    man = {
        "label": LP.LADDER_VERSION,
        "status": "POST_HOC_REVIEWER_MOTIVATED",
        "not_preregistered": True,
        "preregistration_note": (
            "This extension was designed after the reviewer raised the blind-versus-localized "
            "task-format confound. It is post hoc. It must never be described as preregistered."),
        "frozen_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "motivation": (
            "Blind discovery is open-ended and relation-localized verification is a binary verdict, "
            "so the 32.9 pp difference confounds information with response format and chance floor. "
            "This ladder holds the response format, schema, finding budget, token budget, decoding "
            "and scorer constant and varies only how much localization information the prompt "
            "carries."),
        "arms": {
            "BLIND_DISCOVERY": "reused unchanged from the frozen Experiment 3 blind records; no new requests",
            "CATEGORY_TARGETED_DISCOVERY": "new; names the broad defect category only",
            "RELATION_TARGETED_DISCOVERY": "new; names the specific relation, not its state",
        },
        "held_constant": [
            "system prompt (exp2b.protocol.SYSTEM_BLIND)",
            "response schema (exp2br.protocol_br.BLIND_SCHEMA_BR, findings maxItems 5)",
            "max_tokens 4096", "temperature 0", "per-case seed derivation",
            "manuscript text and line numbering (E0 variant)",
            "scorer: exp2b.scoring.label_defective, TRUE_DETECTION only",
        ],
        "models": MODELS,
        "n_relations": len(subset),
        "n_new_requests_planned": len(subset) * len(MODELS) * 2,
        "case_ids": subset,
        "category_text": LP.CATEGORY_TEXT,
        "decision_rules": {
            "primary_outcome": "strict discovery (TRUE_DETECTION) of the tested relation",
            "secondary": ["Recall@1", "Recall@5", "finding precision",
                          "false-positive findings per case"],
            "contrasts": ["category minus blind", "relation minus category", "relation minus blind"],
            "uncertainty": "exact paired counts plus manuscript-cluster bootstrap, 10,000 draws, seed 20261016",
            "monotonicity": "NOT assumed. If category targeting does not help, that is reported. "
                            "If relation targeting does not help, that is reported.",
            "no_outcome_dependent_choices": "Arms, prompts, scorer and contrasts are fixed by this "
                                            "manifest before the first request is issued.",
        },
        "source_code_sha256": {
            "ladder_protocol.py": sha_file(OUT / "code/ladder_protocol.py"),
            "exp2b/protocol.py": sha_file(ROOT / "exp2b/protocol.py"),
            "exp2br/protocol_br.py": sha_file(ROOT / "exp2br/protocol_br.py"),
            "exp2b/scoring.py": sha_file(ROOT / "exp2b/scoring.py"),
            "exp3heldout/ledger.json": sha_file(ROOT / "exp3heldout/ledger.json"),
        },
        "frozen_blind_prompt": {
            "prompt_id": P.BLIND_PROMPT_ID,
            "system_sha256": sha256_text(P.SYSTEM_BLIND),
            "user_template_sha256": sha256_text(P.BLIND_CANDIDATES[P.BLIND_PROMPT_ID]),
            "schema_sha256": sha256_text(canonical(PBR.BLIND_SCHEMA_BR)),
        },
    }

    # per-case inserted sentences, hashed, so the exact stimulus is auditable
    stim = []
    for cid in subset:
        c = cases[cid]
        for arm in LP.ARMS:
            _p, pr = LP.build_arm(arm, {"served_name": "x"}, "[L00001] x\n", c, 1)
            stim.append({"case_id": cid, "family": c["family"], "arm": arm,
                         "inserted_sentence": pr["inserted_sentence"],
                         "sha256": pr["inserted_sentence_sha256"]})
    with (OUT / "ladder/LADDER_STIMULI.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(stim[0])); w.writeheader(); w.writerows(stim)
    man["stimuli_sha256"] = sha_file(OUT / "ladder/LADDER_STIMULI.csv")

    text = json.dumps(man, indent=1, sort_keys=False) + "\n"
    (OUT / "ladder/LADDER_DESIGN_MANIFEST.json").write_text(text)
    print(f"froze LADDER_DESIGN_MANIFEST.json  sha256 {hashlib.sha256(text.encode()).hexdigest()}")
    print(f"planned new requests: {man['n_new_requests_planned']}")
    print(f"stimuli rows: {len(stim)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
