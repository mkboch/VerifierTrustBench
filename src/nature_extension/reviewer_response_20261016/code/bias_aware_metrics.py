#!/usr/bin/env python3
"""B1 + B2: bias-aware relation-localized metrics, and evidence-supported localized accuracy.

Every metric here is computed on the relation-localized (binary verdict) task only. None of them
is comparable to blind discovery, which is open-ended with a different chance floor; that is the
point of computing them.

Definitions, all on the neutral targeted exposure:
  hit (TP)   E0 defective relation judged ISSUE_PRESENT
  miss (FN)  E0 defective relation judged otherwise
  CR (TN)    E1 valid relation judged NO_ISSUE
  FA (FP)    E1 valid relation judged otherwise
  sensitivity = TP/(TP+FN) over E0;  specificity = TN/(TN+FP) over E1
  balanced accuracy = (sensitivity + specificity)/2
  d' = z(sensitivity) - z(FA rate), log-linear corrected: add 0.5 to each cell and 1 to each total
  criterion c = -0.5 * (z(sensitivity) + z(FA rate))      (positive c = conservative)
  MCC over the pooled E0+E1 confusion matrix
"""
from __future__ import annotations
import csv, json, sys, collections
from pathlib import Path
import numpy as np
from scipy.stats import norm

OUT = Path(__file__).resolve().parents[1]
ROWS = list(csv.DictReader((OUT / "data/PROFILE_5SYSTEM_184_ITEMLEVEL.csv").open()))
B12 = list(csv.DictReader((OUT / "data/PROFILE_12SYSTEM_ITEMLEVEL.csv").open()))
for r in ROWS + B12:
    r["correct"] = int(r["correct"])


def metrics(rows, label):
    e0 = [r for r in rows if r["axis"] == "localized_E0"]
    e1 = [r for r in rows if r["axis"] == "localized_E1"]
    sup = [r for r in rows if r["axis"] == "supported_E0"]
    TP = sum(r["correct"] for r in e0); FN = len(e0) - TP
    TN = sum(r["correct"] for r in e1); FP = len(e1) - TN
    if not (e0 and e1):
        return None
    sens, spec = TP / len(e0), TN / len(e1)
    far = FP / len(e1)
    # log-linear correction so d' stays finite at 0/1 cells
    sens_c = (TP + 0.5) / (len(e0) + 1)
    far_c = (FP + 0.5) / (len(e1) + 1)
    dprime = norm.ppf(sens_c) - norm.ppf(far_c)
    crit = -0.5 * (norm.ppf(sens_c) + norm.ppf(far_c))
    num = TP * TN - FP * FN
    den = np.sqrt(float(TP + FP) * (TP + FN) * (TN + FP) * (TN + FN))
    mcc = num / den if den > 0 else float("nan")
    s_num = sum(r["correct"] for r in sup)
    return {"group": label, "n_E0": len(e0), "n_E1": len(e1),
            "TP": TP, "FN": FN, "TN": TN, "FP": FP,
            "sensitivity_E0": round(sens, 4), "specificity_E1": round(spec, 4),
            "false_positive_rate_E1": round(far, 4), "false_negative_rate_E0": round(FN / len(e0), 4),
            "balanced_accuracy": round((sens + spec) / 2, 4),
            "dprime_loglinear": round(float(dprime), 4), "criterion_c": round(float(crit), 4),
            "mcc": round(float(mcc), 4),
            "supported_E0_x": s_num, "supported_E0_n": len(sup),
            "supported_E0_rate": round(s_num / len(sup), 4) if sup else None,
            "localized_E0_rate": round(sens, 4),
            "supported_minus_localized_pp": round(100 * (s_num / len(sup) - sens), 1) if sup else None}


out = []
for dataset, rows, systems in (("primary_184", ROWS, None), ("broad_60", B12, None)):
    sysset = sorted({r["system"] for r in rows})
    for m in sysset:
        r = metrics([x for x in rows if x["system"] == m], m)
        if r:
            out.append({"dataset": dataset, **r})
    r = metrics(rows, "POOLED")
    if r:
        out.append({"dataset": dataset, **r})

with (OUT / "data/LOCALIZED_BIAS_AWARE_METRICS.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)

sup_rows = [{k: v for k, v in r.items() if k in
             ("dataset", "group", "localized_E0_rate", "supported_E0_x", "supported_E0_n",
              "supported_E0_rate", "supported_minus_localized_pp")} for r in out]
with (OUT / "data/LOCALIZED_SUPPORTED_ACCURACY.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(sup_rows[0])); w.writeheader(); w.writerows(sup_rows)

hdr = f"{'dataset':12}{'system':16}{'sens':>7}{'spec':>8}{'balacc':>8}{'d-prime':>9}{'crit c':>8}{'MCC':>7}{'supported':>11}"
print(hdr); print("-" * len(hdr))
for r in out:
    print(f"{r['dataset']:12}{r['group']:16}{100*r['sensitivity_E0']:6.1f}%{100*r['specificity_E1']:7.1f}%"
          f"{100*r['balanced_accuracy']:7.1f}%{r['dprime_loglinear']:9.2f}{r['criterion_c']:8.2f}"
          f"{r['mcc']:7.2f}{100*r['supported_E0_rate']:10.1f}%")
print("\nwrote LOCALIZED_BIAS_AWARE_METRICS.csv and LOCALIZED_SUPPORTED_ACCURACY.csv")
