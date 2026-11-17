#!/usr/bin/env python3
"""Derive docs/data/scorer_audit_items.json from the frozen scorer-assessment records.

PROVENANCE, CORRECTED 2026-11-16
================================

These assessments were previously described in this repository as the work of six human
reviewers. That description was wrong. The first author states that the six assessment
sessions were LANGUAGE-MODEL CHAT SESSIONS: three ChatGPT conversations and three Claude
conversations. No human volunteer, colleague or participant produced them.

The repository holds NO record of the session origin -- no model identifier, no version,
no date, no transcript, no setting. The correction therefore rests on the author's
statement, and the specific session-to-label mapping is NOT VERIFIED from any artifact in
this tree. The response files carry only the opaque labels used at the time.

WHAT THIS MEANS FOR THE SCIENCE
-------------------------------

These are EXPLORATORY AI-SESSION ASSESSMENTS. They are not human validation, not
independent adjudication, and not evidence that the benchmark's labels or its scorer are
correct. Specifically they do NOT establish:

  * a measured scorer false-negative rate;
  * human inter-rater reliability (the agreement statistics describe agreement between
    language-model sessions, whose independence is not established -- three sessions share
    one provider and three share another, and common training data alone would correlate
    them);
  * ground-truth validity of the benchmark.

The per-item counts below are the raw frozen outcomes and are published unchanged. What
changed is the description of what produced them and what may be concluded from them.

TWO ASSESSMENT SETS, both of the SCORER and not of any person:

  blind     60 items, 6 sessions, 360 judgements, on the blind finding-list scorer.
  targeted  30 items, 6 sessions, 180 judgements, on the relation-targeted scorer.

Whether the same six sessions produced both sets is NOT VERIFIED; the two sets were
collected on different dates under different file-naming conventions.

An E0 defect is a perturbation THIS STUDY injected into a sound published manuscript.
Nothing here asserts that any real paper contains an error.
"""
from __future__ import annotations
import csv, hashlib, json, os, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("VTB_ROOT", "")).resolve()
if not (ROOT / "nature_extension").is_dir():
    sys.exit("set VTB_ROOT to the private research tree root")
FS = ROOT / "nature_extension/fair_scoring_validation_20261020"
TV = ROOT / "nature_extension/final_topvenue_validation_20261018"
sys.path.insert(0, str(FS / "code"))
import fairlib as F  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs/data/scorer_audit_items.json"
LEVELS = ["Yes", "Partially", "No", "Ambiguous / Cannot determine"]
NORM = {"yes": "Yes", "partially": "Partially", "partial": "Partially", "no": "No",
        "ambiguous": "Ambiguous / Cannot determine",
        "ambiguous / cannot determine": "Ambiguous / Cannot determine",
        "cannot determine": "Ambiguous / Cannot determine"}


def targeted_items():
    """Aggregate the six per-reviewer response files into per-item category counts.

    The reviewer column and the free-text notes column are read and discarded here; they
    never reach the output. This aggregation IS the de-identification step.
    """
    d = FS / "relation_targeted_scorer_human_review_responses"
    counts = defaultdict(lambda: defaultdict(int))
    sessions = set()
    for p in sorted(d.glob("*.csv")):
        with open(p, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                item = (row.get("item_id") or "").strip()
                raw = (row.get("q1_identifies_tested_relation") or "").strip()
                if not item or not raw:
                    continue
                lvl = NORM.get(raw.lower())
                if lvl is None:
                    sys.exit(f"unmapped rating {raw!r} in {p.name}")
                counts[item][lvl] += 1
                sessions.add((row.get("reviewer") or p.stem).strip())
    sample = json.load(open(FS / "audit/RELATION_TARGETED_AUDIT_SAMPLE.json"))
    meta = {i["audit_id"]: i for i in sample["items"]}
    f = F.Fair()
    papers = sorted({c["paper"] for c in f.cells.values()})
    relations = sorted(f.subset)
    cluster = {p: f"M{i+1:02d}" for i, p in enumerate(papers)}
    relid = {r: f"R{i+1:02d}" for i, r in enumerate(relations)}
    missing = sorted(set(counts) - set(meta))
    if missing:
        sys.exit(f"response rows reference unknown audit ids: {missing[:5]}")
    out = []
    for item in sorted(counts, key=lambda k: meta[k]["audit_id"]):
        c, m = counts[item], meta[item]
        out.append({
            "item": m["audit_id"],
            "stratum": m["category"],
            "stratum_population": m["stratum_population"],
            "stratum_sampled": m["stratum_sampled"],
            "sampling_weight": m["sampling_weight"],
            "family": m["family"],
            "domain": m["domain"],
            "cluster": cluster.get(m["paper"], ""),
            "relation": relid.get(m["case_id"], ""),
            "n_sessions": sum(c.values()),
            "counts": {k: c.get(k, 0) for k in LEVELS},
        })
    return out, len(sessions), sample


def blind_items():
    """The blind audit was already frozen as per-item counts with no reviewer axis."""
    out = []
    with open(TV / "data/BLIND_SCORER_HUMAN_AUDIT_RESULTS.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            out.append({
                "item": row["item_id"],
                "item_kind": row["item_kind"],
                "family": row["family"],
                "domain": row["domain"],
                "n_sessions": int(row["n_reviewers"]),
                "counts": {"Yes": int(row["q1_yes"]), "Partially": int(row["q1_partially"]),
                           "No": int(row["q1_no"]),
                           "Ambiguous / Cannot determine": int(row["q1_ambiguous"])},
                "majority_verdict": row["majority_verdict"],
                "unanimous_binary": int(row["unanimous_binary"]),
            })
    return out


def main() -> int:
    tgt, n_rev, sample = targeted_items()
    bld = blind_items()
    rt = json.load(open(FS / "data/RT_AUDIT_RESULTS.json"))
    ag = json.load(open(TV / "data/AUDIT_AGREEMENT.json"))

    doc = {
        "schema_version": 1,
        "what_this_is": __doc__.strip(),
        "defects_are_synthetic": (
            "An E0 defect is a perturbation THIS STUDY injected into a sound published "
            "manuscript. Nothing here asserts that any real paper contains an error."),
        "provenance": (
            "EXPLORATORY AI-SESSION ASSESSMENT. Six language-model chat sessions "
            "(reported by the first author as three ChatGPT and three Claude "
            "conversations) rated the sampled items. These are NOT human judgements and "
            "are NOT independent validation of the scorer or the benchmark. The session "
            "origin is not documented in any repository artifact and is NOT VERIFIED; "
            "the per-session axis and all free text are withheld because they establish "
            "nothing and could be mistaken for independent replicates."),
        "not_human_validation": (
            "This repository previously described these assessments as the work of six "
            "human reviewers. That description was incorrect and was corrected on "
            "2026-11-16. See CHANGELOG.md."),
        "audits": {
            "targeted": {
                "question": rt["question"],
                "rung": sample["rung"], "state": sample["state"],
                "n_items": len(tgt), "n_sessions": n_rev,
                "total_judgments": sum(i["n_sessions"] for i in tgt),
                "sampling_seed": sample["seed"],
                "population_total_misses": sample["population_total_misses"],
                "strata": sample["stratification"],
                "reweighting_note": sample["reweighting_note"],
                "tie_break_rule": rt["tie_break_rule"],
                "bootstrap": rt["bootstrap"],
                "items": tgt,
            },
            "blind": {
                "question": ("Was the BLIND finding-list scorer right to record this miss "
                             "(or this false positive)?"),
                "n_items": len(bld), "n_sessions": ag["n_reviewers"],
                "total_judgments": sum(i["n_sessions"] for i in bld),
                "items": bld,
            },
        },
        "agreement_between_sessions": {
            "note": ("Agreement BETWEEN LANGUAGE-MODEL SESSIONS. These are not human "
                     "inter-rater reliability statistics and must not be reported as "
                     "such. The sessions are not established to be independent: three "
                     "share one provider and three another, and shared training data "
                     "alone would correlate them, so a kappa computed over them does not "
                     "carry its usual interpretation. Carried for provenance only."),
            "targeted_mean_pairwise_raw_agreement_4level":
                rt["agreement"]["mean_pairwise_raw_agreement_4level"],
            "targeted_mean_pairwise_raw_agreement_binary":
                rt["agreement"]["mean_pairwise_raw_agreement_binary"],
            "blind_pairwise_raw_agreement_4level": ag["pairwise_raw_agreement_4level"],
            "blind_pairwise_raw_agreement_binary": ag["pairwise_raw_agreement_binary"],
        },
        "generated_by": "tools/build_scorer_audit_public.py",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    b = json.dumps(doc, indent=1, sort_keys=False).encode()
    OUT.write_bytes(b)
    print(f"wrote {OUT.relative_to(Path(__file__).resolve().parents[1])}  "
          f"{len(tgt)} targeted + {len(bld)} blind items, {len(b)} bytes")
    print("sha256", hashlib.sha256(b).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
