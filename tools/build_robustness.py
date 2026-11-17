#!/usr/bin/env python3
"""Derive docs/data/robustness.json: the evidence the headline contrast rests on.

Three blocks, all computed from frozen records.

1. FALSE-ALARM INFERENCE. The cost side of the trade-off, with uncertainty. The primary
   interval is the manuscript-cluster bootstrap, because outcomes are grouped by
   manuscript. An exact McNemar p-value is carried alongside as a descriptive companion
   and is explicitly NOT clustered.

2. SCORER-CONFOUND SENSITIVITY. The frozen contrast scores the finding list with a lexical
   matcher and the verdict by exact match, so format and scorer are confounded. Both
   conditions' stored outputs carry cited evidence lines, which supports ONE deterministic
   criterion applied identically to both: did the response cite a line supporting the
   tested relation? Re-scoring both conditions that way gives a SENSITIVITY BOUND on how
   much of the contrast depends on the scoring choice. It is not a decomposition into
   format and scorer components; only an experiment that holds the scorer fixed while
   changing the interface could do that, and none has been run.

3. PER-SYSTEM RESULTS. Pooled statistics hide heterogeneity, and a pooled value is not the
   mean of per-system values. Both are published.
"""
from __future__ import annotations
import collections, hashlib, json, os, random, sys
from pathlib import Path

ROOT = Path(os.environ.get("VTB_ROOT", "")).resolve()
if not (ROOT / "nature_extension").is_dir():
    sys.exit("set VTB_ROOT to the private research tree root")
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from reproducibility import contrasts as C, data as D       # noqa: E402
from reproducibility.estimators import aggregate, rates      # noqa: E402

SEED, DRAWS = 20261016, 10000


def cluster_boot(by, stat):
    ks = sorted(by)
    rng = random.Random(SEED)
    vals = []
    for _ in range(DRAWS):
        samp = []
        for _ in range(len(ks)):
            samp += by[ks[rng.randrange(len(ks))]]
        v = stat(samp)
        if v is not None:
            vals.append(v)
    vals.sort()
    return vals[int(.025 * (len(vals) - 1))], vals[int(.975 * (len(vals) - 1))]


def main() -> int:
    doc, cells = D.load_cells()
    OW = [s["id"] for s in doc["systems"] if s["id"] != "gpt-5.2"]
    LBL = {s["id"]: s["label"] for s in doc["systems"]}
    pairs = C.eligible(cells, "relation", "binary", OW)
    n = len(pairs)

    # ---- 1. false-alarm inference -------------------------------------------------
    fa_a = sum(p["a"]["e1_false_alarm"] for p in pairs)
    fa_b = sum(p["b"]["e1_false_alarm"] for p in pairs)
    b = sum(1 for p in pairs if p["b"]["e1_false_alarm"] and not p["a"]["e1_false_alarm"])
    c_ = sum(1 for p in pairs if p["a"]["e1_false_alarm"] and not p["b"]["e1_false_alarm"])
    both = sum(1 for p in pairs if p["a"]["e1_false_alarm"] and p["b"]["e1_false_alarm"])
    by = collections.defaultdict(list)
    for p in pairs:
        by[p["cluster"]].append(p)
    lo, hi = cluster_boot(by, lambda s: 100 * (
        sum(x["b"]["e1_false_alarm"] for x in s) - sum(x["a"]["e1_false_alarm"] for x in s)
    ) / len(s) if s else None)
    from math import comb
    nd, k = b + c_, min(b, c_)
    p_exact = min(1.0, 2 * sum(comb(nd, i) for i in range(k + 1)) / 2 ** nd) if nd else 1.0

    fa_block = {
        "what_this_is": ("The cost side of the trade-off, with its denominator and its "
                         "uncertainty. Reporting that false alarms 'doubled' without both "
                         "would overstate what 13 extra discordant cells can support."),
        "n_paired_cells": n,
        "relation_targeted_list": {"false_alarms": fa_a, "n": n, "rate_pct": 100 * fa_a / n},
        "relation_localized_verdict": {"false_alarms": fa_b, "n": n, "rate_pct": 100 * fa_b / n},
        "paired_difference_pp": 100 * (fa_b - fa_a) / n,
        "primary_interval": {
            "method": "manuscript-cluster bootstrap",
            "draws": DRAWS, "seed": SEED, "clusters": len(by),
            "ci95_pp": [lo, hi], "excludes_zero": bool(lo > 0 or hi < 0)},
        "paired_discordance": {"verdict_only_b": b, "list_only_c": c_,
                               "both": both, "neither": n - b - c_ - both},
        "exact_mcnemar": {
            "p_value": p_exact, "n_discordant": nd,
            "CAVEAT": ("This test treats all cells as independent. They are NOT: five "
                       "systems x sixty relations nested in twenty-one manuscripts. It "
                       "does NOT account for clustering and must never be presented as "
                       "though it does. The cluster bootstrap above is the primary "
                       "analysis.")},
    }

    # ---- 2. scorer-confound sensitivity (requires the private raw outputs) ---------
    FS = ROOT / "nature_extension/fair_scoring_validation_20261020"
    sys.path.insert(0, str(FS / "code"))
    import fairlib as F
    S = F.S
    f = F.Fair()
    e1f = {}
    for r in F.jl(FS / "e1/e1_openweight_trials.jsonl"):
        if r.get("arm") != "RELATION_TARGETED_DISCOVERY":
            continue
        res = r.get("result") or {}
        if res.get("status") == "OK":
            e1f[(r["model"], r["case_id"])] = (res.get("parsed") or {}).get("findings") or []

    def cited(fl):
        out, bad = [], []
        for x in fl or []:
            out += [v for v in (x.get("evidence_line_ids") or []) if isinstance(v, int)]
            bad += list(x.get("evidence_line_ids_malformed") or [])
        return out, bad

    rows = []
    for cid in sorted(f.subset):
        case = f.cases[cid]
        for s in F.OPENWEIGHT:
            a = f.cells.get((s, "RELATION_TARGETED_FINDING_LIST", cid), {})
            v = f.cells.get((s, "RELATION_LOCALIZED_BINARY_VERDICT", cid), {})
            if not a or not v:
                continue
            if not all(x.get(k) == "OK" for x in (a, v) for k in ("e0_status", "e1_status")):
                continue
            fl1 = e1f.get((s, cid))
            if fl1 is None:
                continue
            i0, b0 = cited(a.get("e0_findings") or [])
            p0 = S.provenance(i0, b0, f.valid_ids(case, "E0"), case["target_lines"])
            i1, b1 = cited(fl1)
            p1 = S.provenance(i1, b1, f.valid_ids(case, "E1"), case["target_lines"])
            rows.append(dict(
                cluster=case["paper"],
                le0f=a.get("e0_correct", 0), ve0f=v.get("e0_correct", 0),
                le1f=a.get("e1_false_alarm", 0), ve1f=v.get("e1_false_alarm", 0),
                le0c=int(bool(a.get("e0_findings")) and p0.get("target_support") in F.SUPPORTED),
                ve0c=int(v.get("e0_verdict") == "ISSUE_PRESENT"
                         and v.get("e0_target_support") in F.SUPPORTED),
                le1c=int(bool(fl1) and p1.get("target_support") in F.SUPPORTED),
                ve1c=int(v.get("e1_verdict") == "ISSUE_PRESENT"
                         and v.get("e1_target_support") in F.SUPPORTED)))

    m = len(rows)
    byc = collections.defaultdict(list)
    for r in rows:
        byc[r["cluster"]].append(r)

    def block(sfx):
        A = rates(sum(r["le0" + sfx] for r in rows), m, sum(r["le1" + sfx] for r in rows), m)
        B = rates(sum(r["ve0" + sfx] for r in rows), m, sum(r["ve1" + sfx] for r in rows), m)
        jl, jh = cluster_boot(byc, lambda s: (
            100 * (rates(sum(r["ve0" + sfx] for r in s), len(s),
                         sum(r["ve1" + sfx] for r in s), len(s))["youden_j"]
                   - rates(sum(r["le0" + sfx] for r in s), len(s),
                           sum(r["le1" + sfx] for r in s), len(s))["youden_j"])) if s else None)
        return {"list_e0_hits": A["hits"], "verdict_e0_hits": B["hits"],
                "list_e1_false_alarms": A["false_alarms"],
                "verdict_e1_false_alarms": B["false_alarms"],
                "raw_difference_pp": 100 * (B["sensitivity"] - A["sensitivity"]),
                "false_alarm_difference_pp": 100 * (B["false_alarm_rate"] - A["false_alarm_rate"]),
                "youden_j_difference_pp": 100 * (B["youden_j"] - A["youden_j"]),
                "youden_j_ci95_pp": [jl, jh],
                "balanced_accuracy_difference_pp": 100 * (B["balanced_accuracy"] - A["balanced_accuracy"]),
                "dprime_difference": B["dprime"] - A["dprime"]}

    fz, cm = block("f"), block("c")
    sc_block = {
        "what_this_is": __doc__.split("2. SCORER-CONFOUND")[1].split("3. PER-SYSTEM")[0].strip(),
        "n_cells": m,
        "common_rule": ("A response is credited with flagging the tested relation iff it "
                        "asserts a problem AND cites a line supporting that relation, "
                        "judged by the frozen provenance function. 'Asserts a problem' "
                        "remains interface-specific -- a list asserts by returning a "
                        "finding, a verdict by returning ISSUE_PRESENT -- and that residual "
                        "difference IS the format effect being retained."),
        "frozen_scorers": fz,
        "common_evidence_localisation_rule": cm,
        "retained_fraction_of_youden_j": cm["youden_j_difference_pp"] / fz["youden_j_difference_pp"],
        "reading": ("Under the common rule the finding list's detections rise sharply AND "
                    "so do its false alarms: the lexical matcher undercounted both, and the "
                    "two errors largely cancel in a discrimination measure. Youden's J is "
                    "therefore robust to the scoring choice while the RAW rates are not. "
                    "This bounds the scorer's contribution; it does not isolate format."),
        "what_this_does_not_establish": (
            "It does not decompose the contrast into a format component and a scorer "
            "component. Replacing one scoring rule with another substitutes a criterion "
            "rather than holding it fixed. A fifth condition holding the scorer constant "
            "while changing only the response interface HAS NOT BEEN RUN."),
    }

    # ---- 3. per-system ------------------------------------------------------------
    def one(sysid, label, group):
        ss = [sysid] if sysid else OW
        pr = C.eligible(cells, "relation", "binary", ss)
        A = rates(*aggregate([p["a"] for p in pr])); B = rates(*aggregate([p["b"] for p in pr]))
        d = C.decompose(cells, "relation", "binary", ss)
        return {"system": sysid or "POOLED_OPEN_WEIGHT", "label": label, "group": group,
                "n_paired": len(pr),
                "relation_e0_hits": A["hits"], "relation_e0_sensitivity_pct": 100 * A["sensitivity"],
                "verdict_e0_hits": B["hits"], "verdict_e0_sensitivity_pct": 100 * B["sensitivity"],
                "relation_e1_false_alarms": A["false_alarms"],
                "relation_e1_false_alarm_pct": 100 * A["false_alarm_rate"],
                "verdict_e1_false_alarms": B["false_alarms"],
                "verdict_e1_false_alarm_pct": 100 * B["false_alarm_rate"],
                "raw_difference_pp": d["raw_detection_difference_pp"],
                "false_alarm_difference_pp": d["false_alarm_difference_pp"],
                "youden_j_difference_pp": d["youden_j_difference_pp"],
                "balanced_accuracy_difference_pp": d["balanced_accuracy_difference_pp"],
                "dprime_difference": B["dprime"] - A["dprime"]}

    per = [one(s, LBL[s], "open-weight") for s in OW]
    per.append(one(None, "Five open-weight systems, pooled", "pooled"))
    per.append(one("gpt-5.2", LBL["gpt-5.2"], "proprietary"))
    mean_raw = sum(r["raw_difference_pp"] for r in per if r["group"] == "open-weight") / len(OW)
    pooled_raw = [r for r in per if r["system"] == "POOLED_OPEN_WEIGHT"][0]["raw_difference_pp"]

    doc_out = {
        "schema_version": 1,
        "defects_are_synthetic": (
            "An E0 defect is a perturbation THIS STUDY injected into a sound published "
            "manuscript. No number here asserts that any real paper contains an error."),
        "false_alarm_inference": fa_block,
        "scorer_confound_sensitivity": sc_block,
        "per_system": {
            "what_this_is": ("Pooled statistics hide heterogeneity. A pooled value is NOT "
                             "the mean of the per-system values and the two are reported "
                             "separately."),
            "pooled_raw_difference_pp": pooled_raw,
            "mean_of_per_system_raw_difference_pp": mean_raw,
            "these_are_different_quantities": True,
            "rows": per},
        "generated_by": "tools/build_robustness.py",
    }
    out = HERE / "docs/data/robustness.json"
    bts = json.dumps(doc_out, indent=1).encode()
    out.write_bytes(bts)
    print(f"wrote docs/data/robustness.json  {len(bts)} bytes")
    print("sha256", hashlib.sha256(bts).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
