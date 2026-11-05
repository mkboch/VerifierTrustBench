#!/usr/bin/env python3
"""Phase 4: construct length-matched IRRELEVANT rationales and FILLER text for the H3 mechanism control.

Deterministic. No model is used to select or tune controls. Run before any inference:
    python nature_extension/phase4_h3_control/build_controls.py
Writes CONTROL_MANIFEST.json (frozen) + a leakage report.

Construction (declared before inference):
  IRRELEVANT rationale = a rationale from a DIFFERENT frozen case, same defect family, DIFFERENT manuscript,
  chosen as the closest token-length match that passes every leakage check. Matching on family holds constant
  "a plausible scientific rationale of the right type" so the contrast isolates whether the rationale actually
  points at THIS relation.

  Leakage checks (all must pass):
    L1  no line ID in the donor equals any target line of the recipient case
    L2  no numeric token in the donor appears in the recipient's target line text or in its checker values
    L3  the recipient's anchor phrase does not appear in the donor
    L4  the donor is not from the recipient's own manuscript
    L5  token length within the frozen tolerance of the text it replaces

  FILLER = deterministic neutral verification note, assembled from a fixed sentence bank to the matched token
  length. Contains no numerals, no line IDs and no relation vocabulary.
"""
from __future__ import annotations
import hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "exp3heldout")); sys.path.insert(0, str(ROOT / "exp2b"))
import design_heldout as D  # noqa: E402

TOL = 0.25          # frozen: donor length within +-25% of the text it replaces
SEED = 20260921     # frozen
OUT = Path(__file__).resolve().parent

_TOK = None
def tok():
    global _TOK
    if _TOK is None:
        from transformers import AutoTokenizer
        _TOK = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B")
    return _TOK

def ntok(s: str) -> int:
    return len(tok()(s)["input_ids"])

LINE_RE = re.compile(r"\bL\d{5}\b")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")

# fixed sentence bank for FILLER: neutral, plausible, no numerals, no line IDs, no relation vocabulary
BANK = [
 "A previous process reviewed the manuscript's presentation conventions before recording its note.",
 "It considered how the section organises its reported material and how terminology is introduced.",
 "It noted the general structure of the surrounding discussion and the order in which material appears.",
 "It observed the typographic conventions used for emphasis and for defined terms in this part of the text.",
 "It recorded that the passage follows the formatting practices used elsewhere in the same manuscript.",
 "It commented on the readability of the surrounding prose and the placement of explanatory material.",
 "It remarked on how the section transitions between descriptive and summarising material.",
 "It noted the use of standard phrasing conventions for introducing supporting material in this field.",
]

def filler_for(target_tokens: int) -> str:
    out = []
    i = 0
    while ntok(" ".join(out)) < target_tokens and i < 200:
        out.append(BANK[i % len(BANK)]); i += 1
    # trim back one sentence if we overshot the tolerance band
    while len(out) > 1 and ntok(" ".join(out[:-1])) >= target_tokens * (1 - TOL):
        out = out[:-1]
    return " ".join(out)

def leakage_ok(donor: dict, recip: dict, donor_text: str) -> tuple[bool, list[str]]:
    fails = []
    if donor["paper"] == recip["paper"]:
        fails.append("L4_same_manuscript")
    tgt_ids = {f"L{n:05d}" for n in recip["target_lines"]}
    if set(LINE_RE.findall(donor_text)) & tgt_ids:
        fails.append("L1_target_line_id")
    recip_nums = set()
    for v in (recip.get("values") or {}).values():
        recip_nums |= set(NUM_RE.findall(str(v)))
    for e in recip["edits"].get("E0", []) + recip["edits"].get("E2", []):
        recip_nums |= set(NUM_RE.findall(str(e.get("new", "")) + " " + str(e.get("old", ""))))
    if set(NUM_RE.findall(donor_text)) & recip_nums:
        fails.append("L2_shared_numeric_token")
    anchor = (recip.get("anchor") or "").strip()
    if len(anchor) >= 6 and anchor.lower() in donor_text.lower():
        fails.append("L3_anchor_in_donor")
    return (not fails), fails

def main():
    plan = D.Plan()
    subset = plan.matrix_subset()
    allcases = {c["case_id"]: c for c in plan.cases}
    # donor pool: every rationale of every case in the FULL ledger (not just the subset)
    pool = []
    for c in plan.cases:
        for st in ("E0", "E1"):
            for pol in ("true", "false"):
                txt = c["rationales"][st][pol]
                pool.append({"case_id": c["case_id"], "paper": c["paper"], "family": c["family"],
                             "domain": c["domain"], "state": st, "polarity": pol, "text": txt,
                             "ntok": ntok(txt)})
    manifest = {"seed": SEED, "tolerance": TOL, "n_subset_cases": len(subset),
                "construction": "donor rationale, same family, different manuscript, closest token-length match "
                                "passing leakage checks L1-L5; filler from a fixed neutral sentence bank",
                "leakage_checks": ["L1_target_line_id", "L2_shared_numeric_token", "L3_anchor_in_donor",
                                   "L4_same_manuscript", "L5_length_tolerance"],
                "cases": {}}
    rejected = []
    for c in subset:
        entry = {"paper": c["paper"], "family": c["family"], "domain": c["domain"], "states": {}}
        for st in ("E0", "E1"):
            ref = c["rationales"][st]["true"]
            n_ref = ntok(ref)
            lo, hi = n_ref * (1 - TOL), n_ref * (1 + TOL)
            cands = [d for d in pool
                     if d["family"] == c["family"] and d["paper"] != c["paper"] and lo <= d["ntok"] <= hi]
            cands.sort(key=lambda d: (abs(d["ntok"] - n_ref), d["case_id"], d["state"], d["polarity"]))
            chosen = None
            for d in cands:
                ok, fails = leakage_ok(d, c, d["text"])
                if ok:
                    chosen = d; break
                rejected.append({"recipient": c["case_id"], "state": st, "donor": d["case_id"], "fails": fails})
            if chosen is None:  # widen family constraint, same domain, still different manuscript
                cands = [d for d in pool if d["paper"] != c["paper"] and lo <= d["ntok"] <= hi]
                cands.sort(key=lambda d: (abs(d["ntok"] - n_ref), d["case_id"], d["state"], d["polarity"]))
                for d in cands:
                    ok, fails = leakage_ok(d, c, d["text"])
                    if ok:
                        chosen = d; chosen = {**d, "relaxed": "family_constraint_relaxed"}; break
            fill = filler_for(n_ref)
            entry["states"][st] = {
                "reference_rationale_ntok": n_ref,
                "irrelevant_rationale": chosen["text"] if chosen else None,
                "irrelevant_donor": {k: chosen[k] for k in ("case_id", "paper", "family", "state", "polarity",
                                                            "ntok")} if chosen else None,
                "irrelevant_relaxed": chosen.get("relaxed") if chosen else None,
                "length_delta_tokens": (chosen["ntok"] - n_ref) if chosen else None,
                "filler": fill, "filler_ntok": ntok(fill),
                "filler_length_delta_tokens": ntok(fill) - n_ref,
            }
        manifest["cases"][c["case_id"]] = entry
    n_ok = sum(1 for c in manifest["cases"].values() for s in c["states"].values() if s["irrelevant_rationale"])
    n_relaxed = sum(1 for c in manifest["cases"].values() for s in c["states"].values() if s["irrelevant_relaxed"])
    deltas = [s["length_delta_tokens"] for c in manifest["cases"].values() for s in c["states"].values()
              if s["length_delta_tokens"] is not None]
    fdeltas = [s["filler_length_delta_tokens"] for c in manifest["cases"].values() for s in c["states"].values()]
    manifest["summary"] = {"slots": len(subset) * 2, "irrelevant_assigned": n_ok, "family_relaxed": n_relaxed,
                           "donor_length_delta": {"min": min(deltas), "max": max(deltas),
                                                  "mean_abs": sum(abs(d) for d in deltas) / len(deltas)},
                           "filler_length_delta": {"min": min(fdeltas), "max": max(fdeltas),
                                                   "mean_abs": sum(abs(d) for d in fdeltas) / len(fdeltas)},
                           "donor_candidates_rejected_for_leakage": len(rejected)}
    txt = json.dumps(manifest, indent=1, sort_keys=True)
    (OUT / "CONTROL_MANIFEST.json").write_text(txt + "\n")
    (OUT / "LEAKAGE_REJECTIONS.json").write_text(json.dumps(rejected, indent=1) + "\n")
    print(json.dumps(manifest["summary"], indent=1))
    print("manifest sha256:", hashlib.sha256(txt.encode()).hexdigest()[:16])

if __name__ == "__main__":
    main()
