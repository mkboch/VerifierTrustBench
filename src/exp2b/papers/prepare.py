#!/usr/bin/env python3
"""Prepare selected papers: extract arXiv source, flatten, normalise -> exp2b/papers/<id>/E1.tex (+ SOURCE.json).

    python exp2b/papers/prepare.py 2609.03933 2609.04261 ...
"""
import hashlib, json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "exp2b")); sys.path.insert(0, str(ROOT / "exp2b/papers"))
import normalize as N
import screen_arxiv as S

for aid in sys.argv[1:]:
    d = S.SRC / aid
    data = (d / "eprint.bin").read_bytes()
    files = S.extract(d, data)
    mains = [k for k, v in files.items() if k.endswith(".tex") and re.search(r"^\s*\\documentclass", v, re.M)]
    assert len(mains) == 1, mains
    text, missing = N.flatten(mains[0], files)
    body = N.normalize(text)
    out = ROOT / "exp2b/papers" / aid
    out.mkdir(parents=True, exist_ok=True)
    (out / "E1.tex").write_text(body)
    meta = {"arxiv_id": aid, "source_url": f"https://arxiv.org/src/{aid}", "source_sha256": hashlib.sha256(data).hexdigest(),
            "source_bytes": len(data), "main_file": mains[0], "unresolved_inputs": missing,
            "normalized_sha256": hashlib.sha256(body.encode()).hexdigest(), "normalized_lines": body.count("\n"),
            "normalizer_sha256": hashlib.sha256((ROOT / "exp2b/normalize.py").read_bytes()).hexdigest()}
    (out / "SOURCE.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(aid, meta["normalized_lines"], meta["normalized_sha256"][:12])
