#!/usr/bin/env python3
"""Derive docs/data/scorer_audit_items.json from the frozen human scorer audits.

TWO audits, both of the SCORER and not of any person:

  blind     60 items, 6 reviewers, 360 judgments. Asks whether the blind finding-list
            scorer was right to record a miss (or a false positive).
  targeted  30 items, 6 reviewers, 180 judgments. Asks the same question of the
            relation-targeted finding-list scorer, which is the rung the headline
            contrast depends on.

WHAT IS PUBLISHED, AND WHY ONLY THIS

Per ITEM, the number of reviewers choosing each category. Nothing else. That is enough to
recompute every item-level statistic the manuscript reports -- majority verdicts, unanimity,
stratum false-negative rates, the reweighted rate and its bootstrap interval, and Fleiss'
kappa, which depends only on per-item category counts.

Deliberately NOT published, because it is not de-identifiable in a group of six named
colleagues and no consent covering publication exists:

  * the reviewer axis -- per-reviewer endorsement rates, and the pairwise agreement matrix
    keyed to reviewer pairs. Mean pairwise raw agreement therefore CANNOT be recomputed from
    this file; it is carried as a retained audited aggregate and labelled as one.
  * free-text reviewer notes.
  * the audited items themselves: the manuscript text, the model's finding list and the
    reviewer-facing evidence summaries. Items appear only as opaque labels.

An E0 defect is a perturbation THIS STUDY injected into a sound published manuscript. An
audited "miss" is a scorer judgement about a model's output on a perturbed manuscript. No
item here asserts that any real paper contains an error.
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
    reviewers = set()
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
                reviewers.add((row.get("reviewer") or p.stem).strip())
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
            "n_reviewers": sum(c.values()),
            "counts": {k: c.get(k, 0) for k in LEVELS},
        })
    return out, len(reviewers), sample


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
                "n_reviewers": int(row["n_reviewers"]),
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
        "human_data_policy": (
            "Per-item category counts only. The reviewer axis and all free text are "
            "withheld: six named colleagues are not de-identifiable along that axis and no "
            "consent covering publication of individual judgements exists."),
        "audits": {
            "targeted": {
                "question": rt["question"],
                "rung": sample["rung"], "state": sample["state"],
                "n_items": len(tgt), "n_reviewers": n_rev,
                "total_judgments": sum(i["n_reviewers"] for i in tgt),
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
                "n_items": len(bld), "n_reviewers": ag["n_reviewers"],
                "total_judgments": sum(i["n_reviewers"] for i in bld),
                "items": bld,
            },
        },
        "retained_audited_aggregates": {
            "note": ("These depend on the withheld reviewer axis and CANNOT be recomputed "
                     "from the per-item counts above. They are carried as audited "
                     "aggregates, not as recomputable values."),
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
