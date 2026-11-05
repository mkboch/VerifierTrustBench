#!/usr/bin/env python3
"""2E: score and analyse the frontier ladder with the SAME frozen scorers as the open-weight run.

Finding-list rungs: exp2b.scoring.label_defective == TRUE_DETECTION.
Verdict rung:       parsed verdict equals the deterministic gold.
Refusals are recorded as REFUSAL and excluded from scoring; they are never counted as misses.
"""
from __future__ import annotations
import collections, csv, json, re, sys
from pathlib import Path
from decimal import Decimal, getcontext
from math import comb
import numpy as np

getcontext().prec = 60
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
RR = ROOT / "nature_extension/reviewer_response_20261016"
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
import design_heldout as D, scoring as S, client as C  # noqa: E402

SEED, NBOOT = 20261016, 10000
plan = D.Plan(); cases = {c["case_id"]: c for c in plan.cases}
RUNGS = ["BLIND_FINDING_LIST", "CATEGORY_TARGETED_FINDING_LIST",
         "RELATION_TARGETED_FINDING_LIST", "RELATION_LOCALIZED_BINARY_VERDICT"]


def parse_json(txt):
    if not txt:
        return None
    t = txt.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-z]*\n?", "", t); t = re.sub(r"\n?```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def norm_ids(raw):
    out, bad = [], []
    for x in raw or []:
        if isinstance(x, int):
            out.append(x); continue
        m = re.match(r"^\s*\[?L?(\d{1,5})\]?\s*$", str(x))
        out.append(int(m.group(1))) if m else bad.append(x)
    return out, bad


rows, spend = [], collections.defaultdict(float)
for prov in ("openai", "anthropic"):
    f = OUT / f"frontier/frontier_{prov}_trials.jsonl"
    if not f.exists():
        continue
    recs = []
    for line in f.open():
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    # a later record for the same key supersedes an earlier one (recovery of a client-side failure)
    latest = {}
    for r in recs:
        latest[r["key"]] = r
    for r in recs:
        spend[prov] += r.get("cost_usd", 0.0)      # every issued request is paid for
    for r in latest.values():
        c = cases[r["case_id"]]
        base = {"provider": prov, "model": r["model"], "rung": r["rung"], "case_id": r["case_id"],
                "paper": r["paper"], "domain": r["domain"], "family": r["case_family"],
                "status": r["status"], "input_tokens": r.get("input_tokens", 0),
                "output_tokens": r.get("output_tokens", 0), "cost_usd": r.get("cost_usd", 0)}
        if not r["status"].startswith("OK"):
            # Distinguish a policy refusal from an ordinary technical failure. stop_reason
            # "max_tokens" with no text block is a truncation, which the frozen protocol already
            # counts as a technical failure; only stop_reason "refusal" is a refusal.
            st = r["status"]
            if st.startswith("REFUSAL") and r.get("stop_reason") != "refusal":
                st = f"TECHNICAL_FAILURE:{r.get('stop_reason')}"
            rows.append({**base, "status": st, "scored": 0, "detected": "", "hit_rank": "",
                         "n_findings": "", "false_positive_findings": ""})
            continue
        p = parse_json(r.get("content"))
        if p is None:
            rows.append({**base, "status": "PARSE_FAILED", "scored": 0, "detected": "",
                         "hit_rank": "", "n_findings": "", "false_positive_findings": ""})
            continue
        _, valid = plan.paper_text(c, "E0")
        if r["rung"] == "RELATION_LOCALIZED_BINARY_VERDICT":
            v = p.get("verdict") or p.get("Verdict")
            rows.append({**base, "scored": 1, "detected": int(v == c["truth"]["E0"]),
                         "hit_rank": "", "n_findings": "", "false_positive_findings": ""})
        else:
            fnd = p.get("findings") or []
            for x in fnd:
                ids, bad = norm_ids(x.get("evidence_line_ids"))
                x["evidence_line_ids"], x["evidence_line_ids_malformed"] = ids, bad
                x.setdefault("allegation", ""); x.setdefault("evidence_summary", "")
            lab, feats = S.label_defective(fnd, c, plan.ledger, valid)
            hit = next((i + 1 for i, ft in enumerate(feats) if ft["L"] and ft["V"] and ft["R"]), None)
            fp = sum(1 for ft in feats if not ft["L"] and not ft["V"])
            rows.append({**base, "scored": 1, "detected": int(lab == "TRUE_DETECTION"),
                         "hit_rank": hit or "", "n_findings": len(fnd),
                         "false_positive_findings": fp})

with (OUT / "data/FRONTIER_ITEMLEVEL.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

print("=" * 96)
print(f"{'provider/model':34}{'rung':40}{'scored':>8}{'refused':>9}{'detect':>9}")
print("=" * 96)
summary = {}
for prov in sorted({r["provider"] for r in rows}):
    mdl = next(r["model"] for r in rows if r["provider"] == prov)
    summary[prov] = {"model": mdl, "spend_usd": round(spend[prov], 4), "rungs": {}}
    for rung in RUNGS:
        sub = [r for r in rows if r["provider"] == prov and r["rung"] == rung]
        if not sub:
            continue
        sc = [r for r in sub if r["scored"] == 1]
        ref = sum(1 for r in sub if str(r["status"]).startswith("REFUSAL"))
        tech = sum(1 for r in sub if str(r["status"]).startswith(("TECHNICAL_FAILURE", "ERROR", "PARSE_FAILED")))
        det = sum(r["detected"] for r in sc) if sc else 0
        summary[prov]["rungs"][rung] = {
            "n_attempted": len(sub), "n_scored": len(sc), "n_refused": ref,
            "n_technical_failure": tech,
            "detected": det, "pct": round(100 * det / len(sc), 1) if sc else None,
            "findings_per_case": round(sum(r["n_findings"] for r in sc if r["n_findings"] != "") /
                                       max(1, sum(1 for r in sc if r["n_findings"] != "")), 2)
                                 if any(r["n_findings"] != "" for r in sc) else None,
            "fp_findings_per_case": round(sum(r["false_positive_findings"] for r in sc
                                              if r["false_positive_findings"] != "") /
                                          max(1, sum(1 for r in sc if r["false_positive_findings"] != "")), 2)
                                    if any(r["false_positive_findings"] != "" for r in sc) else None,
            "recall_at_1": sum(1 for r in sc if r["hit_rank"] != "" and int(r["hit_rank"]) <= 1),
            "recall_at_5": sum(1 for r in sc if r["hit_rank"] != "" and int(r["hit_rank"]) <= 5),
        }
        d = summary[prov]["rungs"][rung]
        pct = f"{d['pct']}%" if d["pct"] is not None else "n/a"
        print(f"{prov+'/'+mdl:34}{rung:40}{d['n_scored']:>8}{ref:>9}{det:>5}/{d['n_scored']:<4}{pct:>8}")
    print(f"{'':34}{'measured spend':40}{'':>8}{'':>9}${spend[prov]:.3f}")


def exact_p(b, c):
    n = b + c
    if n == 0:
        return Decimal(1)
    k = min(b, c)
    return min(2 * sum(Decimal(comb(n, i)) for i in range(k + 1)) / (Decimal(2) ** n), Decimal(1))


idx = {(r["provider"], r["case_id"], r["rung"]): r for r in rows if r["scored"] == 1}
paper_of = {r["case_id"]: r["paper"] for r in rows}


def paired(prov, a, b):
    units = [cid for (p, cid, rg) in idx if p == prov and rg == a and (prov, cid, b) in idx]
    if len(units) < 5:
        return None
    recs = [{"a": idx[(prov, u, a)]["detected"], "b": idx[(prov, u, b)]["detected"],
             "paper": paper_of[u]} for u in units]
    ao = sum(1 for r in recs if r["a"] and not r["b"])
    bo = sum(1 for r in recs if r["b"] and not r["a"])
    n = len(recs)
    byp = collections.defaultdict(list)
    for r in recs:
        byp[r["paper"]].append(r)
    ps = sorted(byp); rng = np.random.default_rng(SEED); vals = []
    for _ in range(NBOOT):
        pick = rng.integers(0, len(ps), len(ps))
        pool = [x for i in pick for x in byp[ps[i]]]
        vals.append(100 * (sum(1 for r in pool if r["a"] and not r["b"]) -
                           sum(1 for r in pool if r["b"] and not r["a"])) / len(pool))
    v = np.asarray(vals)
    return {"n": n, "rate_a": round(100 * sum(1 for r in recs if r["a"]) / n, 1),
            "rate_b": round(100 * sum(1 for r in recs if r["b"]) / n, 1),
            "diff_pp": round(100 * (ao - bo) / n, 2), "a_only": ao, "b_only": bo,
            "exact_p": f"{exact_p(ao, bo):.4E}",
            "lo": round(float(np.percentile(v, 2.5)), 2),
            "hi": round(float(np.percentile(v, 97.5)), 2), "n_manuscripts": len(ps)}


CONTRASTS = [
    ("category information, format held", "CATEGORY_TARGETED_FINDING_LIST", "BLIND_FINDING_LIST"),
    ("exact-relation increment", "RELATION_TARGETED_FINDING_LIST", "CATEGORY_TARGETED_FINDING_LIST"),
    ("total information, format held", "RELATION_TARGETED_FINDING_LIST", "BLIND_FINDING_LIST"),
    ("RESPONSE FORMAT, information held", "RELATION_LOCALIZED_BINARY_VERDICT", "RELATION_TARGETED_FINDING_LIST"),
]
print("\n" + "=" * 96)
print(f"{'provider':12}{'contrast':40}{'n':>5}{'diff':>9}{'exact p':>12}{'cluster 95% CI':>20}")
print("=" * 96)
for prov in summary:
    for lab, a, b in CONTRASTS:
        r = paired(prov, a, b)
        if r is None:
            print(f"{prov:12}{lab:40}{'—  not measurable (rung refused)':>46}")
            summary[prov].setdefault("contrasts", {})[lab] = None
            continue
        summary[prov].setdefault("contrasts", {})[lab] = r
        print(f"{prov:12}{lab:40}{r['n']:>5}{r['diff_pp']:>+9.2f}{r['exact_p']:>12}"
              f"   [{r['lo']:+.2f}, {r['hi']:+.2f}]")

json.dump({"seed": SEED, "n_bootstrap": NBOOT, "summary": summary,
           "total_spend_usd": {k: round(v, 4) for k, v in spend.items()}},
          (OUT / "data/FRONTIER_RESULTS.json").open("w"), indent=1)
print(f"\ntotal measured spend: " +
      ", ".join(f"{k} ${v:.3f}" for k, v in spend.items()))
print("wrote data/FRONTIER_RESULTS.json and data/FRONTIER_ITEMLEVEL.csv")
