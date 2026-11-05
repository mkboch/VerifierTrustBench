#!/usr/bin/env python3
"""Derive docs/data/fair_scoring_cells.json from the frozen research records.

This script runs in the private research tree, not in a clone of this repository: it
reads the frozen E0 records and the E1 fair-scoring records through fairlib, the canonical
loader, and emits the minimal per-cell table the playground needs to recompute the
four-rung fair-scoring analysis in the visitor's browser.

WHAT IS PUBLISHED, PER CELL
    system, rung, cluster, relation, defect family, domain,
    whether the response was scoreable in E0 and in E1,
    the binary E0 hit, the binary E1 false alarm, and the provenance-gated E0 hit.

WHAT IS NOT PUBLISHED
    No model generation. No manuscript text. No finding text. No evidence line. No prompt
    content. No human-participant record.

    Manuscripts carry OPAQUE CLUSTER LABELS (M01 ... M21), and relations carry opaque
    labels (R01 ... R60). The cluster label is all the estimand needs -- the bootstrap
    resamples manuscripts, it does not read them. The label-to-arXiv-identifier mapping is
    deliberately not published here: an E0 cell is a defect THIS STUDY INJECTED into a
    sound published manuscript, and a table naming third-party papers beside defect labels
    invites exactly the misreading that those manuscripts are flawed. Publishing the
    mapping is an author decision, not a build-script decision; adding it later is a
    one-file change that does not alter any number below.

    Binary correctness labels are derived measurements, not model output, so publishing
    them redistributes nothing belonging to a model provider or to an arXiv author.
"""
from __future__ import annotations
import hashlib, json, os, sys
from pathlib import Path

ROOT = Path(os.environ.get("VTB_ROOT", "")).resolve()
if not (ROOT / "nature_extension").is_dir():
    sys.exit("set VTB_ROOT to the private research tree root (it must contain "
             "nature_extension/ and runs/)")
FS = ROOT / "nature_extension/fair_scoring_validation_20261020"
sys.path.insert(0, str(FS / "code"))
import fairlib as F  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs/data/fair_scoring_cells.json"

RUNGS = [
    ("blind", "BLIND_FINDING_LIST", "Blind finding list",
     "Nothing is pointed at. The system sees the whole manuscript and is asked what, if "
     "anything, is wrong with it.",
     "Ranked list of findings, each with a described defect and cited lines."),
    ("category", "CATEGORY_TARGETED_FINDING_LIST", "Category-targeted finding list",
     "The system is told which FAMILY of defect to look for (for example 'a statistical "
     "reporting error'), but not where or which relation.",
     "Ranked list of findings, each with a described defect and cited lines."),
    ("relation", "RELATION_TARGETED_FINDING_LIST", "Relation-targeted finding list",
     "The system is told the exact relation under test, in words, and asked to report what "
     "it finds.",
     "Ranked list of findings, each with a described defect and cited lines."),
    ("binary", "RELATION_LOCALIZED_BINARY_VERDICT", "Relation-localized binary verdict",
     "The same exact relation as the rung above. The information is identical; only the "
     "response interface changes.",
     "A binary verdict on the named relation, with cited evidence lines."),
]

SYSTEM_LABELS = {
    "qwen38_27": "Qwen3-VL-like open-weight system A (27B class)",
    "qwen36_27": "Open-weight system B (27B class)",
    "gemma4_12": "Open-weight system C (12B class)",
    "granite42_30": "Open-weight system D (30B class)",
    "qwen3_8": "Open-weight system E (8B class)",
    "gpt-5.2": "GPT-5.2 (proprietary, reasoning_effort=none)",
}


def main() -> int:
    f = F.Fair()
    papers = sorted({c["paper"] for c in f.cells.values()})
    relations = sorted(f.subset)
    cluster = {p: f"M{i + 1:02d}" for i, p in enumerate(papers)}
    relid = {r: f"R{i + 1:02d}" for i, r in enumerate(relations)}

    systems = list(F.OPENWEIGHT) + [F.FRONTIER]
    fields = ["system", "rung", "cluster", "relation", "family", "domain",
              "e0_scoreable", "e1_scoreable", "e0_hit", "e1_false_alarm", "e0_prov_gated"]
    rows = []
    for s in systems:
        for short, long, *_ in RUNGS:
            for c in f.rows(s, long):
                ok0 = int(c.get("e0_status") == "OK")
                ok1 = int(c.get("e1_status") == "OK")
                rows.append([
                    s, short, cluster[c["paper"]], relid[c["case_id"]],
                    c["family"], c["domain"], ok0, ok1,
                    int(c.get("e0_correct", 0)) if ok0 else None,
                    int(c.get("e1_false_alarm", 0)) if ok1 else None,
                    (int(c.get("e0_prov_gated", 0)) if (ok0 and short == "binary") else None),
                ])
    rows.sort(key=lambda r: (r[0], r[1], r[3]))

    doc = {
        "schema_version": 1,
        "what_this_is":
            "Per-cell binary outcomes for the four-rung E0/E1 fair-scoring analysis. One "
            "row is one (system, rung, relation). E0 is the perturbed state, in which the "
            "tested relation has been broken; E1 is the manuscript exactly as published, "
            "in which the same relation is sound. Every quantity the playground shows for "
            "this analysis is recomputed from these rows in your browser.",
        "defects_are_synthetic":
            "An E0 defect is a perturbation THIS STUDY introduced into a sound published "
            "manuscript in order to test verifiers. No row asserts, or should be read as "
            "asserting, that any real published manuscript contains an error.",
        "what_is_not_here":
            "No model generation, manuscript text, finding text, evidence line, prompt "
            "content or human-participant record. Manuscripts appear only as opaque "
            "cluster labels; the label-to-arXiv mapping is not published here.",
        "scoring":
            "Scored by the frozen scorers only: exp2b/scoring.py label_defective for an E0 "
            "finding list, label_clean for an E1 finding list on the tested relation, and "
            "the stored verdict for the binary rung. A finding about some other part of "
            "the manuscript is not counted either way. Nothing was rescored for this "
            "release.",
        "generated_by": "tools/build_fair_scoring_public.py",
        "cluster_unit": "manuscript",
        "n_clusters": len(papers),
        "n_relations": len(relations),
        "systems": [{"id": s, "label": SYSTEM_LABELS.get(s, s),
                     "proprietary": s == F.FRONTIER} for s in systems],
        "rungs": [{"id": a, "record_key": b, "label": c, "exposure": d,
                   "response_interface": e} for a, b, c, d, e in RUNGS],
        "families": sorted({r[4] for r in rows}),
        "domains": sorted({r[5] for r in rows}),
        "fields": fields,
        "cells": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, separators=(",", ":"))
    OUT.write_text(text + "\n")
    print(f"wrote {OUT.relative_to(Path(__file__).resolve().parents[1])}  "
          f"{len(rows)} cells, {len(text) + 1} bytes")
    print("sha256", hashlib.sha256((text + "\n").encode()).hexdigest())
    return 0


sys.exit(main())
