#!/usr/bin/env python3
"""Deterministic preparation + data-only screening of held-out candidates (no model inference).

    python exp3heldout/prepare_screen.py            # all candidates with a downloaded source

Steps per candidate (frozen before any candidate was processed):
  S1 source readable, exactly one main file with \\documentclass
  S2 \\input/\\include resolved inside the archive (<= 2 unresolved, none of them .tex bodies)
  S3 normalised manuscript (exp2b/normalize.py, unchanged and hash-checked) is non-trivial: >= 250 numbered lines
  S4 token band: 7,000 <= Qwen3-8B tokens of the line-numbered manuscript <= 24,000 (identical band to Experiment 2B;
     guarantees the frozen blind request prompt + 4,096 + 256 fits 32,768 for every primary model)
  S5 quantitative content: >= 2 tabular environments containing numeric cells, >= 40 decimal numbers,
     >= 5 resolvable \\ref/\\eqref, >= 1 percentage or p-value/CI pattern
  S6 no unrecoverable LaTeX (normalisation runs; numbering stable; no unbalanced \\begin/\\end in the body)
Writes exp3heldout/papers/<id>/E1.tex + SOURCE.json and appends exp3heldout/pool/screen.jsonl.
"""
from __future__ import annotations
import os

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2b"))
import normalize as N  # noqa: E402  (frozen)

POOL = ROOT / "exp3heldout/pool"
SRC = Path(os.environ.get("VTB_SOURCE_DIR", "sources/heldout"))
OUTDIR = ROOT / "exp3heldout/papers"
TOK_MIN, TOK_MAX = 7000, 24000
_TOK = None


def tokenizer():
    global _TOK
    if _TOK is None:
        from transformers import AutoTokenizer
        _TOK = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B")
    return _TOK


def read_files(d: Path) -> dict[str, str]:
    out = {}
    for p in d.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".tex", ".ltx", ".sty", ".bbl", ".txt") and p.name != "source.raw":
            try:
                out[str(p.relative_to(d))] = p.read_text(errors="replace")
            except Exception:  # noqa: BLE001
                pass
    return out


def indicators(text: str) -> dict:
    tabs = re.findall(r"\\begin\{(tabular\*?|tabularx|longtable)\}(.*?)\\end\{\1\}", text, re.S)
    numeric_tabs = sum(1 for _, body in tabs if len(re.findall(r"\d+\.\d+", body)) >= 4)
    labels = set(re.findall(r"\\label\{([^}]+)\}", text))
    refs = [r for r in re.findall(r"\\(?:ref|eqref|autoref|cref|Cref)\{([^}]+)\}", text)]
    return {"tabulars": len(tabs), "numeric_tabulars": numeric_tabs,
            "decimals": len(set(re.findall(r"(?<![\w.])\d+\.\d+(?![\w])", text))),
            "percentages": len(re.findall(r"\d[\d.]*\s*\\?%", text)),
            "pvalues": len(re.findall(r"[pP]\s*[<=>]\s*0?\.\d+|\bCI\b|confidence interval", text)),
            "labels": len(labels), "refs": len(refs),
            "resolvable_refs": sum(1 for r in refs if r in labels),
            "sections": len(re.findall(r"\\section\{", text))}


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    src_rows = [json.loads(l) for l in (POOL / "source.jsonl").read_text().splitlines()]
    meta = {json.loads(l)["id"]: json.loads(l) for l in (POOL / "meta.jsonl").read_text().splitlines()}
    out_path = POOL / "screen.jsonl"
    done = {json.loads(l)["id"] for l in out_path.read_text().splitlines()} if out_path.exists() else set()
    tok = tokenizer()
    with out_path.open("a") as fh:
        for row in src_rows:
            pid = row["id"]
            if pid in done:
                continue
            rec = {"id": pid, "domain": row["domain"], "primary": row["primary"],
                   "title": meta.get(pid, {}).get("title"), "v1_date": meta.get(pid, {}).get("v1_date"),
                   "authors": meta.get(pid, {}).get("authors", [])[:12], "subjects": meta.get(pid, {}).get("subjects"),
                   "source_kind": row.get("kind")}
            try:
                d = SRC / pid
                files = read_files(d)
                mains = [k for k, v in files.items() if re.search(r"^\s*\\documentclass", v, re.M)]
                rec["main_candidates"] = mains
                if row.get("kind") in (None, "download_failed", "unreadable"):
                    rec.update(eligible=False, reason="source_unavailable")
                elif len(mains) != 1:
                    rec.update(eligible=False, reason=f"main_files={len(mains)}")
                else:
                    text, missing = N.flatten(mains[0], files)
                    body = N.normalize(text)
                    numbered, valid = N.number(body)
                    ntok = len(tok(numbered)["input_ids"])
                    ind = indicators(body)
                    begins = len(re.findall(r"\\begin\{", body))
                    ends = len(re.findall(r"\\end\{", body))
                    rec.update({"unresolved_inputs": missing, "lines": len(valid), "tokens_qwen3_8b": ntok,
                                "balanced_envs": begins == ends, **ind})
                    fails = []
                    if [m for m in missing if m.endswith((".tex", ".ltx"))] or len(missing) > 2:
                        fails.append("unresolved_inputs")
                    if len(valid) < 250:
                        fails.append("too_few_lines")
                    if not (TOK_MIN <= ntok <= TOK_MAX):
                        fails.append(f"tokens_out_of_band({ntok})")
                    if ind["numeric_tabulars"] < 2:
                        fails.append("few_numeric_tables")
                    if ind["decimals"] < 40:
                        fails.append("few_decimals")
                    if ind["resolvable_refs"] < 5:
                        fails.append("few_refs")
                    if ind["percentages"] + ind["pvalues"] < 1:
                        fails.append("no_pct_or_stats")
                    if begins != ends:
                        fails.append("unbalanced_envs")
                    rec["eligible"] = not fails
                    rec["reason"] = ";".join(fails) or "screen_pass"
                    if not fails:
                        od = OUTDIR / pid
                        od.mkdir(parents=True, exist_ok=True)
                        (od / "E1.tex").write_text(body)
                        raw = (SRC / pid / "source.raw").read_bytes()
                        (od / "SOURCE.json").write_text(json.dumps({
                            "arxiv_id": pid, "source_url": f"https://arxiv.org/e-print/{pid}",
                            "source_sha256": hashlib.sha256(raw).hexdigest(), "source_bytes": len(raw),
                            "main_file": mains[0], "unresolved_inputs": missing,
                            "normalized_sha256": hashlib.sha256(body.encode()).hexdigest(),
                            "normalized_lines": len(valid), "tokens_qwen3_8b": ntok,
                            "normalizer_sha256": hashlib.sha256((ROOT / "exp2b/normalize.py").read_bytes()).hexdigest(),
                        }, indent=1) + "\n")
            except Exception as e:  # noqa: BLE001
                rec.update(eligible=False, reason=f"exception:{type(e).__name__}", error=repr(e)[:300])
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(pid, rec["domain"], rec.get("tokens_qwen3_8b"), rec["eligible"], rec["reason"], flush=True)


if __name__ == "__main__":
    main()
