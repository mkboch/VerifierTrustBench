#!/usr/bin/env python3
"""Aggregate per-model technical preflight results into exp2bbroad/VALIDATION_GATE.md."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2bbroad"))
import models_broad as MB
res = ROOT / "exp2bbroad/results"
L = ["# Experiment 2B-broad — technical validation gate", "",
     "Technical checks only; scientific accuracy is never a criterion (`FROZEN_DESIGN.md`). P6 repeatability is reported, not gated.", "",
     "| Model | Family | Regime | P1 context | P2 server | P3 targeted schema | P4 blind schema | P5 final answer | P7 validity | P8 line IDs | Gate | Repeatability |",
     "|---|---|---|---|---|---|---|---|---|---|---|---|"]
rows = []
for m in MB.RUN_HERE:
    p = res / f"preflight_{m}.json"
    if not p.exists():
        L.append(f"| {m} | {MB.MODELS[m]['family']} | {MB.MODELS[m]['reasoning_mode']} | — | — | — | — | — | — | — | not run | — |")
        continue
    d = json.loads(p.read_text())
    if "checks" not in d:
        L.append(f"| {m} | {MB.MODELS[m]['family']} | {MB.MODELS[m]['reasoning_mode']} | — | — | — | — | — | — | — | FAIL ({d.get('reason')}) | — |")
        continue
    c = d["checks"]
    rep = c["P6_repeatability"]
    lab = "byte-identical" if rep["all_byte_identical"] else ("verdict-identical only" if rep["all_verdict_identical"] else "verdicts differ")
    L.append(f"| {m} | {d['family']} | {d['reasoning_mode']} | " + " | ".join(
        ("pass" if c[k]["pass"] else "FAIL") for k in ("P1_context", "P2_server", "P3_targeted_schema", "P4_blind_schema",
                                                        "P5_final_answer", "P7_validity", "P8_line_ids")) +
             f" | {'PASS' if d['gate_pass'] else 'FAIL'} | {lab} |")
    rows.append((m, d))
L += ["", "## Context headroom (largest total = prompt + max_tokens + 256, limit 32,768)", ""]
for m, d in rows:
    worst = max(((p, k, v["total"]) for p, r in d["checks"]["P1_context"]["papers"].items() for k, v in r.items()), key=lambda x: x[2])
    L.append(f"- {m}: {worst[2]} tokens ({worst[1]} on {worst[0]})")
L += ["", "## Repeatability probes (3 identical repeats x 3 probes)", ""]
for m, d in rows:
    rep = d["checks"]["P6_repeatability"]
    detail = "; ".join(f"{pr['probe']}: bytes {'same' if pr['byte_identical'] else 'differ'}"
                       + (f", verdict {'same' if pr['verdict_identical'] else 'differs'}" if pr["kind"] == "targeted"
                          else f", finding count {'same' if pr['n_findings_identical'] else 'differs'}") for pr in rep["probes"])
    L.append(f"- {m} ({d['determinism_label']}): {detail}")
(ROOT / "exp2bbroad/VALIDATION_GATE.md").write_text("\n".join(L) + "\n")
print("\n".join(L[:8]))
