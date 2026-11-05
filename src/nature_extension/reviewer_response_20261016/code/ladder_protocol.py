#!/usr/bin/env python3
"""B4 REVIEWER_MOTIVATED_LOCALIZATION_LADDER — protocol definition.

POST HOC. Motivated by reviewer comment on the blind-vs-localized task-format confound.
This is NOT preregistered and must never be described as such.

Three arms, one scoring metric:

  BLIND_DISCOVERY              reused unchanged from the frozen Experiment 3 blind records
  CATEGORY_TARGETED_DISCOVERY  new: names the broad defect category only
  RELATION_TARGETED_DISCOVERY  new: names the specific relation, without revealing its state

The two new arms differ from the frozen blind request in exactly one way: a single neutral
sentence inserted before the manuscript. Everything else -- system prompt, response schema,
maximum finding count (5), max_tokens, temperature, seed derivation and the scorer -- is the
frozen blind configuration, imported rather than copied.

Scoring for all three arms is identical: strict discovery (exp2b.scoring.label_defective ==
TRUE_DETECTION) of the tested relation within the returned finding list.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))

import protocol as P          # noqa: E402  frozen 2B protocol
import protocol_br as PBR     # noqa: E402  frozen bounded blind schema
from client import canonical, sha256_text  # noqa: E402

LADDER_VERSION = "REVIEWER_MOTIVATED_LOCALIZATION_LADDER-v1.0"
ARMS = ("CATEGORY_TARGETED_DISCOVERY", "RELATION_TARGETED_DISCOVERY")

# Neutral category descriptions. Each names the family in ordinary scientific words and says
# nothing about whether a defect is present, where it is, or what its value would be.
CATEGORY_TEXT = {
    "arithmetic": "a quantity that should follow arithmetically from other quantities stated nearby",
    "numerical": "a numeric value that is reported in more than one place",
    "cross_reference": "a citation of a table, figure or section label",
    "claim_evidence": "a claim in the prose and the evidence it points to",
    "method_result": "a stated methodological choice and the result that depends on it",
    "statistical": "a statistical statement such as a significance claim, interval or range",
}

_CATEGORY_LINE = (
    "For this audit, concentrate on one kind of relation: {description}. "
    "Examine relations of that kind throughout the manuscript and report any that are inconsistent. "
    "If you find none of that kind, return an empty list.\n"
)

_RELATION_LINE = (
    "For this audit, concentrate on one specific relation in the manuscript: {description}. "
    "Determine whether that relation is internally consistent, and report it as a finding if it is not. "
    "If it is consistent, return an empty list.\n"
)


def neutral_description(case: dict) -> str:
    """The relation descriptor shown in the relation-targeted arm.

    Uses the frozen ledger `title`, which names the family and an anchoring phrase from the
    surrounding prose. Verified across the subset to contain none of the perturbed E0 token
    values, so it cannot hand the model the answer.
    """
    return case["title"]


def build_arm(arm: str, model_cfg: dict, numbered_paper: str, case: dict, seed: int):
    """Return (payload, provenance) for one ladder request.

    Built by taking the frozen bounded-blind request and inserting one sentence. The manuscript,
    schema, token budget, temperature and seed are untouched.
    """
    if arm not in ARMS:
        raise ValueError(arm)
    payload, prov = PBR.build_blind_br(model_cfg, numbered_paper, seed)
    if arm == "CATEGORY_TARGETED_DISCOVERY":
        extra = _CATEGORY_LINE.format(description=CATEGORY_TEXT[case["family"]])
    else:
        extra = _RELATION_LINE.format(description=neutral_description(case))

    user = payload["messages"][1]["content"]
    marker = "<MANUSCRIPT>"
    assert user.count(marker) == 1, "blind template shape changed; refusing to build"
    head, tail = user.split(marker, 1)
    payload = dict(payload)
    payload["messages"] = [payload["messages"][0],
                           {"role": "user", "content": head + extra + "\n" + marker + tail}]
    prov = dict(prov)
    prov.update({
        "ladder_version": LADDER_VERSION, "ladder_arm": arm,
        "inserted_sentence": extra.strip(),
        "inserted_sentence_sha256": sha256_text(extra),
        "request_sha256": sha256_text(canonical(payload)),
        "block_fingerprint": sha256_text(canonical(payload)),
    })
    return payload, prov


def self_check() -> None:
    """The new arms must differ from the frozen blind request only in the inserted sentence."""
    cfg = {"served_name": "test"}
    paper = "[L00001] alpha\n[L00002] beta\n"
    case = {"family": "arithmetic", "title": "arithmetic relation on alpha and beta"}
    base, _ = PBR.build_blind_br(cfg, paper, 7)
    for arm in ARMS:
        p, _pr = build_arm(arm, cfg, paper, case, 7)
        assert p["messages"][0] == base["messages"][0], "system prompt changed"
        for k in ("seed", "max_tokens", "temperature", "response_format", "model"):
            assert p.get(k) == base.get(k), f"{k} changed in {arm}"
        b, n = base["messages"][1]["content"], p["messages"][1]["content"]
        assert n.count("<MANUSCRIPT>") == 1 and paper in n, "manuscript mangled"
        # removing the inserted sentence must restore the frozen blind text exactly
        ins = _pr["inserted_sentence"]
        assert n.replace(ins + "\n\n", "", 1) == b, f"{arm} differs by more than the inserted sentence"
    print("ladder_protocol self-check: PASS "
          "(arms differ from the frozen blind request by exactly one inserted sentence)")


if __name__ == "__main__":
    self_check()
