#!/usr/bin/env python3
"""Phase 1: verify the six returned relation-targeted scorer-audit response files.

Checks structure, completeness and correspondence to the FROZEN audit packet. Imputes
nothing. If anything is missing or malformed the script says exactly what, and the
analysis step refuses to run.

Reviewer anonymity: files are mapped to Reviewer 1..6 by the reviewer column inside the
file, which is the label the package itself assigned. No other metadata is read or
reported.
"""
from __future__ import annotations
import csv, hashlib, json, re
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
SRC = OUT / "relation_targeted_scorer_human_review_responses"
SAMPLE = OUT / "audit/RELATION_TARGETED_AUDIT_SAMPLE.json"
PKG = OUT / "relation_targeted_scorer_audit_packages"
EXPECTED_SAMPLE = "6c5ebdecdb204f79ceea6d8fcf5d50b7cf94a9667ff2a92280a5409c24cc74b2"

Q1 = {"Yes", "Partially", "No", "Ambiguous / Cannot determine"}
Q2 = {"Yes, appears genuine", "No, not a real issue", "Ambiguous / Cannot determine",
      "Not applicable"}
Q3 = {"High", "Medium", "Low"}
COLS = ["reviewer", "item_id", "q1_identifies_tested_relation",
        "q2_other_problem_genuine", "q3_confidence", "notes"]

rep = {"label": "RELATION_TARGETED_AUDIT_RESPONSE_VERIFICATION", "files": [],
       "problems": [], "status": None}

# --- the frozen packet must be unchanged
ssha = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
rep["frozen_sample_sha256"] = ssha
rep["frozen_sample_unchanged"] = (ssha == EXPECTED_SAMPLE)
if ssha != EXPECTED_SAMPLE:
    rep["problems"].append(f"frozen audit sample changed: {ssha} != {EXPECTED_SAMPLE}")
frozen = json.loads(SAMPLE.read_text())
FROZEN_IDS = [it["audit_id"] for it in frozen["items"]]
rep["n_frozen_items"] = len(FROZEN_IDS)

# --- the distributed packet must be unchanged too
pm = PKG / ".package_manifest.json"
if pm.exists():
    man = json.loads(pm.read_text())
    rep["package_manifest_sample_sha256"] = man.get("source_sample_sha256")
    rep["package_built_from_frozen_sample"] = (man.get("source_sample_sha256") == EXPECTED_SAMPLE)
    rep["package_item_order_matches_frozen"] = (sorted(man.get("item_order", []))
                                                == sorted(FROZEN_IDS))
    if not rep["package_built_from_frozen_sample"]:
        rep["problems"].append("the distributed package was not built from the frozen sample")
    cur = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(PKG.glob("Reviewer_*/review.html"))}
    rep["n_packages_on_disk"] = len(cur)
    rep["packages_identical_on_disk"] = len(set(cur.values())) == 1
else:
    rep["problems"].append("package manifest missing; cannot confirm what was distributed")

# --- the returned files
files = sorted(p for p in SRC.glob("*.csv"))
rep["n_files"] = len(files)
if len(files) != 6:
    rep["problems"].append(f"expected 6 response files, found {len(files)}")

rows_by_rev, seen_labels = {}, []
for p in files:
    info = {"filename": p.name, "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    # utf-8-sig tolerates a BOM, which a spreadsheet export may add
    with p.open(encoding="utf-8-sig", newline="") as fh:
        rdr = csv.DictReader(fh)
        hdr = rdr.fieldnames or []
        rows = [r for r in rdr if (r.get("item_id") or "").strip()]
    info["header_ok"] = (hdr == COLS)
    if not info["header_ok"]:
        rep["problems"].append(f"{p.name}: header {hdr} != {COLS}")
    labels = {(r.get("reviewer") or "").strip() for r in rows}
    info["reviewer_labels_in_file"] = sorted(labels)
    if len(labels) != 1:
        rep["problems"].append(f"{p.name}: {len(labels)} distinct reviewer labels {sorted(labels)}")
    label = sorted(labels)[0] if labels else p.stem
    if not re.fullmatch(r"Reviewer_[1-6]", label):
        rep["problems"].append(f"{p.name}: reviewer label {label!r} is not Reviewer_1..6")
    seen_labels.append(label)
    info["reviewer"] = label

    ids = [(r["item_id"] or "").strip() for r in rows]
    info["n_rows"] = len(rows)
    info["n_distinct_ids"] = len(set(ids))
    dups = [i for i, c in Counter(ids).items() if c > 1]
    unknown = sorted(set(ids) - set(FROZEN_IDS))
    missing = sorted(set(FROZEN_IDS) - set(ids))
    info["duplicate_ids"] = sorted(dups)
    info["unknown_ids"] = unknown
    info["missing_ids"] = missing
    if dups:
        rep["problems"].append(f"{p.name}: duplicate item ids {sorted(dups)}")
    if unknown:
        rep["problems"].append(f"{p.name}: unknown item ids {unknown}")
    if missing:
        rep["problems"].append(f"{p.name}: missing item ids {missing}")

    bad_q1 = [r["item_id"] for r in rows
              if (r.get("q1_identifies_tested_relation") or "").strip() not in Q1]
    blank_q1 = [r["item_id"] for r in rows
                if not (r.get("q1_identifies_tested_relation") or "").strip()]
    bad_q2 = [r["item_id"] for r in rows
              if (r.get("q2_other_problem_genuine") or "").strip() not in Q2
              and (r.get("q2_other_problem_genuine") or "").strip()]
    bad_q3 = [r["item_id"] for r in rows
              if (r.get("q3_confidence") or "").strip() not in Q3
              and (r.get("q3_confidence") or "").strip()]
    info["malformed_q1"] = bad_q1
    info["blank_mandatory_q1"] = blank_q1
    info["malformed_q2"] = bad_q2
    info["malformed_q3"] = bad_q3
    info["n_with_notes"] = sum(1 for r in rows if (r.get("notes") or "").strip())
    for nm, bad in (("q1", bad_q1), ("q2", bad_q2), ("q3", bad_q3)):
        if bad:
            rep["problems"].append(f"{p.name}: malformed {nm} on {bad}")
    if blank_q1:
        rep["problems"].append(f"{p.name}: blank mandatory q1 on {blank_q1}")

    info["q1_distribution"] = dict(Counter(
        (r.get("q1_identifies_tested_relation") or "").strip() for r in rows))
    rep["files"].append(info)
    rows_by_rev[label] = rows

dupl = [l for l, c in Counter(seen_labels).items() if c > 1]
if dupl:
    rep["problems"].append(f"duplicate reviewer labels across files: {dupl}")
rep["reviewers"] = sorted(rows_by_rev)
rep["all_six_present"] = sorted(rows_by_rev) == [f"Reviewer_{i}" for i in range(1, 7)]
if not rep["all_six_present"]:
    rep["problems"].append(f"reviewer set is {sorted(rows_by_rev)}, expected Reviewer_1..6")

rep["total_judgments"] = sum(len(v) for v in rows_by_rev.values())
rep["expected_judgments"] = 6 * len(FROZEN_IDS)
rep["status"] = "PASS" if not rep["problems"] else "FAIL"
(OUT / "audit/RT_RESPONSE_VERIFICATION.json").write_text(json.dumps(rep, indent=1) + "\n")

print(f"status: {rep['status']}   files={rep['n_files']}  "
      f"judgments={rep['total_judgments']}/{rep['expected_judgments']}")
print(f"frozen sample unchanged: {rep['frozen_sample_unchanged']}")
print(f"package built from frozen sample: {rep.get('package_built_from_frozen_sample')}  "
      f"packages identical on disk: {rep.get('packages_identical_on_disk')}")
for f in rep["files"]:
    print(f"  {f['reviewer']:11s} rows={f['n_rows']:3d} ids={f['n_distinct_ids']:3d} "
          f"notes={f['n_with_notes']:3d} dup={len(f['duplicate_ids'])} "
          f"unk={len(f['unknown_ids'])} miss={len(f['missing_ids'])} "
          f"blankQ1={len(f['blank_mandatory_q1'])}")
if rep["problems"]:
    print("\nPROBLEMS:")
    for x in rep["problems"]:
        print("  -", x)
