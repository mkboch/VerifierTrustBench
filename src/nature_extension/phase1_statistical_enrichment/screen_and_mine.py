#!/usr/bin/env python3
"""Phase 1: screen the newly harvested papers and mine statistical-consistency cases.

Reuses the FROZEN Experiment 3 screening helpers (read_files, indicators, token band) and the FROZEN statistical
checkers. Two miners are applied, both producing family='statistical':
  * mine_cases.mine_statistical  -- frozen Experiment 3 miner (significance-claim vs p-value; range containment)
  * mine_stat_ext.mine_ci        -- Phase 1 extraction upgrade for the SAME chk_range relation in LaTeX CI form

No model is involved. No Experiment 3 artifact is modified.
"""
from __future__ import annotations
import os
import json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / "exp3heldout")); sys.path.insert(0, str(ROOT / "exp2b"))
import prepare_screen as PS     # frozen helpers
import mine_cases as M          # frozen miners
import checkers as CK           # frozen checkers
import normalize as N           # frozen numbering
import mine_stat_ext as X       # Phase 1 extraction upgrade

SRC = Path(os.environ.get("VTB_SOURCE_DIR", "sources/statistical_enrichment"))
OUT = HERE / "mined"


def main():
    OUT.mkdir(exist_ok=True)
    dirs = sorted(d for d in SRC.iterdir() if d.is_dir())
    tk = PS.tokenizer()
    stats = Counter()
    results = {}
    for i, d in enumerate(dirs, 1):
        pid = d.name
        try:
            files = PS.read_files(d)
        except Exception:
            stats["read_error"] += 1; continue
        mains = [k for k, v in files.items() if "\\documentclass" in v]
        if len(mains) != 1:
            stats["main_files"] += 1; continue
        body = files[mains[0]]
        try:
            body = M.flatten(body, files) if hasattr(M, "flatten") else body
        except Exception:
            pass
        try:
            numbered, _ = N.number(body)
        except Exception:
            stats["number_error"] += 1; continue
        ntok = len(tk(numbered)["input_ids"])
        if not (PS.TOK_MIN <= ntok <= PS.TOK_MAX):
            stats["tokens_out_of_band"] += 1; continue
        lines = CK.lines_of(numbered)
        if len(lines) < 250:
            stats["too_few_lines"] += 1; continue
        secs, envs = {}, {}
        cands = []
        try:
            cands += M.mine_statistical(lines, secs, body, envs)
        except Exception:
            stats["frozen_miner_error"] += 1
        try:
            cands += X.mine_ci(lines)
        except Exception:
            stats["ext_miner_error"] += 1
        stats["papers_screened"] += 1
        stats["candidates"] += len(cands)
        keep, used = [], set()
        for c in cands:
            if set(c["target_lines"]) & used:
                continue
            try:
                v = M.validate(c, body)
            except Exception:
                stats["validate_error"] += 1; continue
            if not v:
                stats["validate_failed"] += 1; continue
            used |= set(c["target_lines"])
            keep.append({**c, "checker_fn": c["spec"]["fn"]})
            stats["validated"] += 1
        if keep:
            results[pid] = {"tokens": ntok, "n": len(keep), "cases": keep}
            stats["papers_with_cases"] += 1
        if i % 100 == 0:
            print(f"  {i}/{len(dirs)} screened={stats['papers_screened']} validated={stats['validated']}",
                  flush=True)
    summary = {"dirs": len(dirs), **dict(stats),
               "validated_total": sum(v["n"] for v in results.values()),
               "by_checker": dict(Counter(c["checker_fn"] for v in results.values() for c in v["cases"]))}
    (OUT / "phase1_mined.json").write_text(json.dumps({"summary": summary, "papers": results}, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
