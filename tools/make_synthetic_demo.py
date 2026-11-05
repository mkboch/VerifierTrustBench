#!/usr/bin/env python3
"""Generate docs/data/synthetic_demo_cells.json -- a FABRICATED dataset for the demo.

WHAT THIS IS
    A machine-generated example in the same shape as a real fair-scoring cell table, so
    that the methodology demonstration on the public site has something to compute on.
    Every outcome is drawn from a random number generator by this script. No model was run.
    No manuscript was read. No number here came from the study.

WHY IT EXISTS
    The public repository ships software, not experimental results. Without some input the
    four-rung analysis cannot be demonstrated at all, and a site that only describes a
    method is much harder to check than one you can run. A clearly fabricated fixture
    solves that without publishing a single measured outcome.

HOW IT IS KEPT DISTINGUISHABLE FROM EVIDENCE
    - the filename says synthetic;
    - the document carries "synthetic": true and a refusal-to-be-mistaken warning string;
    - the systems are named "Demo system A".."E", which match nothing in the study;
    - tests/test_synthetic_fixture.py fails the build if any of that is weakened, and
      scripts/audit_public_release.py refuses to publish a data file that is not marked
      synthetic.

REPRODUCING IT
    python tools/make_synthetic_demo.py            # deterministic; seed below

REPLACING IT WITH YOUR OWN RUN
    If you have run the pipeline yourself, tools/build_fair_scoring_public.py turns your
    own frozen records into a file of exactly this shape, and the site will load it from
    disk. Nothing has to go through this script or through us.
"""
from __future__ import annotations
import argparse, hashlib, json, random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs/data/synthetic_demo_cells.json"
SEED = 1104

RUNGS = [
    ("blind", "BLIND_FINDING_LIST", "Blind finding list",
     "Nothing is pointed at. The system sees the whole manuscript and is asked what, if "
     "anything, is wrong with it.",
     "Ranked list of findings, each with a described defect and cited lines."),
    ("category", "CATEGORY_TARGETED_FINDING_LIST", "Category-targeted finding list",
     "The system is told which FAMILY of defect to look for, but not where or which "
     "relation.",
     "Ranked list of findings, each with a described defect and cited lines."),
    ("relation", "RELATION_TARGETED_FINDING_LIST", "Relation-targeted finding list",
     "The system is told the exact relation under test, in words, and asked to report "
     "what it finds.",
     "Ranked list of findings, each with a described defect and cited lines."),
    ("binary", "RELATION_LOCALIZED_BINARY_VERDICT", "Relation-localized binary verdict",
     "The same exact relation as the rung above. The information is identical; only the "
     "response interface changes.",
     "A binary verdict on the named relation, with cited evidence lines."),
]

SYSTEMS = [(f"demo_system_{c.lower()}", f"Demo system {c}") for c in "ABCDE"]
FAMILIES = ["arithmetic", "claim_evidence", "cross_reference", "method_result",
            "numerical", "statistical"]
DOMAINS = ["A_demo_domain", "B_demo_domain", "C_demo_domain"]

# Fabricated generative parameters. These are INVENTED to make the demonstration show the
# shapes a reader should learn to look for -- a rung that raises sensitivity and its false
# alarms together, and one that does not. They are not estimates of anything.
PARAMS = {
    "blind":    {"hit": 0.14, "fa": 0.02},
    "category": {"hit": 0.24, "fa": 0.02},
    "relation": {"hit": 0.22, "fa": 0.05},
    "binary":   {"hit": 0.50, "fa": 0.09},
}
SYSTEM_SKILL = {"demo_system_a": +0.06, "demo_system_b": +0.02, "demo_system_c": -0.05,
                "demo_system_d": -0.02, "demo_system_e": -0.01}
N_CLUSTERS, N_PER_CLUSTER = 21, 3
P_UNSCOREABLE = 0.01


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    clusters = [f"M{i + 1:02d}" for i in range(N_CLUSTERS)]
    relations = []
    for ci, c in enumerate(clusters):
        for j in range(N_PER_CLUSTER):
            relations.append({
                "relation": f"R{ci * N_PER_CLUSTER + j + 1:02d}", "cluster": c,
                "family": FAMILIES[(ci + j) % len(FAMILIES)],
                "domain": DOMAINS[ci % len(DOMAINS)],
                # a per-relation difficulty offset, so that relations within one cluster
                # are correlated -- which is the whole reason the bootstrap clusters
                "difficulty": rng.gauss(0, 0.06),
            })

    fields = ["system", "rung", "cluster", "relation", "family", "domain",
              "e0_scoreable", "e1_scoreable", "e0_hit", "e1_false_alarm", "e0_prov_gated"]
    rows = []
    for sid, _label in SYSTEMS:
        for short, _long, *_ in RUNGS:
            p = PARAMS[short]
            for r in relations:
                ok0 = 0 if rng.random() < P_UNSCOREABLE else 1
                ok1 = 0 if rng.random() < P_UNSCOREABLE else 1
                ph = min(0.97, max(0.01, p["hit"] + SYSTEM_SKILL[sid] + r["difficulty"]))
                pf = min(0.97, max(0.00, p["fa"] - r["difficulty"] / 3))
                hit = int(rng.random() < ph) if ok0 else None
                fa = int(rng.random() < pf) if ok1 else None
                prov = (int(hit and rng.random() < 0.8)
                        if (ok0 and short == "binary") else None)
                rows.append([sid, short, r["cluster"], r["relation"], r["family"],
                             r["domain"], ok0, ok1, hit, fa, prov])
    rows.sort(key=lambda x: (x[0], x[1], x[3]))

    doc = {
        "schema_version": 1,
        "synthetic": True,
        "warning":
            "SYNTHETIC DEMONSTRATION DATA. Every value in this file was generated by a "
            "random number generator in tools/make_synthetic_demo.py. No model produced "
            "any of it, no manuscript was examined, and nothing here is a measurement. It "
            "exists so that the analysis code can be demonstrated and tested. Do not cite "
            "it, do not compare it with the study's published results, and do not treat "
            "any quantity computed from it as a finding.",
        "what_this_is":
            "A fabricated table in the shape of a four-rung E0/E1 fair-scoring cell table. "
            "One row is one (system, rung, relation).",
        "not_experimental_evidence":
            "The study's measured outcomes are not published in this repository. See "
            "README.md, section 'What this repository does and does not contain'.",
        "generated_by": "tools/make_synthetic_demo.py",
        "seed": a.seed,
        "cluster_unit": "manuscript (fabricated)",
        "n_clusters": len(clusters),
        "n_relations": len(relations),
        "systems": [{"id": i, "label": n, "proprietary": False} for i, n in SYSTEMS],
        "rungs": [{"id": x, "record_key": y, "label": z, "exposure": e,
                   "response_interface": f} for x, y, z, e, f in RUNGS],
        "families": sorted({r[4] for r in rows}),
        "domains": sorted({r[5] for r in rows}),
        "fields": fields,
        "cells": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, separators=(",", ":")) + "\n"
    OUT.write_text(text)
    print(f"wrote {OUT.name}: {len(rows)} synthetic cells, {len(text)} bytes, seed {a.seed}")
    print("sha256", hashlib.sha256(text.encode()).hexdigest())
    return 0


raise SystemExit(main())
