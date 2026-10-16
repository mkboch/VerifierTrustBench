#!/usr/bin/env python3
"""Held-out paper harvesting (no model inference anywhere in this file).

    python exp3heldout/harvest.py list      # build the candidate list from arXiv monthly listings
    python exp3heldout/harvest.py meta      # fetch abs-page metadata (authors, dates, categories)
    python exp3heldout/harvest.py source    # download + extract source archives to /scratch

Frozen before any candidate was retrieved (see exp3heldout/PAPER_SELECTION.md):
  * window: first posted 2026-07-01 .. 2026-09-15 (arXiv IDs 2607.*, 2608.*, 2609.* with submission date in window)
  * domain -> primary-category map DOMAIN_CATS below
  * listing order only (no ranking by content), primary-category entries only
  * per category at most MAX_PER_CAT candidates, scanned in listing order from the oldest month first
Outputs: exp3heldout/pool/listing.jsonl, pool/meta.jsonl, $VTB_SOURCE_DIR/<id>/
"""
from __future__ import annotations
import os

import json
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "exp3heldout/pool"
SRC = Path(os.environ.get("VTB_SOURCE_DIR", "sources/heldout"))
MONTHS = ["2026-07", "2026-08", "2026-09"]
WINDOW = ("2026-07-01", "2026-09-15")
MAX_PER_CAT = 14

DOMAIN_CATS = {
    "A_ml_ai": ["cs.LG", "cs.AI", "stat.ML"],
    "B_vision_signal": ["cs.CV", "eess.IV", "eess.SP"],
    "C_biomedical": ["physics.med-ph", "q-bio.QM", "q-bio.NC", "q-bio.PE", "q-bio.MN", "q-bio.TO"],
    "D_statistics": ["stat.ME", "stat.AP", "stat.CO"],
    "E_physics_engineering": ["physics.comp-ph", "physics.app-ph", "eess.SY", "physics.bio-ph", "physics.flu-dyn"],
}

# Expansion round 1 (declared 2026-09-17, before any model inference): the first pass (14 candidates per category)
# left the biomedical and statistics strata with only two screen-passing papers each, so the per-category scan depth is
# raised and three further categories are added in the sparse strata. The publication window is unchanged.
PER_CAT = {"cs.LG": 14, "cs.AI": 14, "stat.ML": 40, "cs.CV": 14, "eess.IV": 40, "eess.SP": 40,
           "physics.med-ph": 70, "q-bio.QM": 70, "q-bio.NC": 70, "q-bio.PE": 50, "q-bio.MN": 50, "q-bio.TO": 50,
           "stat.ME": 70, "stat.AP": 70, "stat.CO": 50,
           "physics.comp-ph": 45, "physics.app-ph": 45, "eess.SY": 45, "physics.bio-ph": 45, "physics.flu-dyn": 45}
EXCLUDED_IDS = {"2609.03933", "2609.04261", "2609.01018", "2609.00473", "2609.01675"}  # Experiment 2B cohort


def get(url, tries=6, timeout=180):
    err = None
    for i in range(tries):
        r = subprocess.run(["curl", "-s", "-L", "--max-time", str(timeout), "-A",
                            "Mozilla/5.0 (compatible; VerifierTrustBench/3-heldout)", "-w", "\\n%{http_code}", url],
                           capture_output=True)
        body, _, code = r.stdout.rpartition(b"\n")
        if r.returncode == 0 and code.strip() == b"200":
            return body
        err = RuntimeError(f"curl rc={r.returncode} http={code.strip().decode(errors='replace')} {url}")
        time.sleep(90 if code.strip() == b"429" else 4 * (i + 1))
    raise err


def cmd_list():
    POOL.mkdir(parents=True, exist_ok=True)
    out_path = POOL / "listing.jsonl"
    seen = {json.loads(l)["id"] for l in out_path.read_text().splitlines()} if out_path.exists() else set()
    with out_path.open("a") as fh:
        for domain, cats in DOMAIN_CATS.items():
            for cat in cats:
                n = 0
                cap = PER_CAT.get(cat, MAX_PER_CAT)
                for month in MONTHS:
                    if n >= cap:
                        break
                    try:
                        html = get(f"https://arxiv.org/list/{cat}/{month}?skip=0&show=500").decode("utf-8", "replace")
                    except Exception as e:  # noqa: BLE001
                        print("LIST FAIL", cat, month, e, flush=True)
                        continue
                    for block in re.split(r"<dt>", html)[1:]:
                        if n >= cap:
                            break
                        m = re.search(r'href ?="/abs/([0-9]{4}\.[0-9]{4,5})"', block)
                        prim = re.search(r'primary-subject">[^<]*\(([^)]+)\)', block)
                        title = re.search(r"Title:</span>\s*(.*?)\s*</div>", block, re.S)
                        if not m or not prim or prim.group(1) != cat:
                            continue
                        pid = m.group(1)
                        if pid in seen or pid in EXCLUDED_IDS:
                            continue
                        seen.add(pid)
                        n += 1
                        rec = {"id": pid, "title": re.sub(r"\s+", " ", title.group(1)) if title else None,
                               "primary": cat, "domain": domain, "listing_month": month}
                        fh.write(json.dumps(rec) + "\n")
                        fh.flush()
                    time.sleep(2)
                print(f"{domain} {cat}: {n} candidates", flush=True)


def cmd_meta():
    recs = [json.loads(l) for l in (POOL / "listing.jsonl").read_text().splitlines()]
    out_path = POOL / "meta.jsonl"
    done = {json.loads(l)["id"] for l in out_path.read_text().splitlines()} if out_path.exists() else set()
    with out_path.open("a") as fh:
        for r in recs:
            if r["id"] in done:
                continue
            try:
                html = get(f"https://arxiv.org/abs/{r['id']}").decode("utf-8", "replace")
            except Exception as e:  # noqa: BLE001
                print("META FAIL", r["id"], e, flush=True)
                continue
            authors = re.findall(r'href="/a/[^"]*"[^>]*>([^<]+)</a>|searchtype=author">([^<]+)</a>', html)
            authors = [a or b for a, b in authors]
            sub = re.search(r"\[v1\][^<]*?(\d{1,2}\s+\w{3}\s+20\d\d)", html) or re.search(r"Submitted on (\d{1,2}\s+\w{3}\s+20\d\d)", html)
            cats = re.findall(r'class="primary-subject">([^<]+)</span>|/list/([a-zA-Z\-\.]+)/recent', html)
            subj = re.search(r'subjects">(.*?)</td>', html, re.S)
            rec = {**r, "authors": authors[:40], "v1_date": sub.group(1) if sub else None,
                   "subjects": re.sub(r"<[^>]+>|\s+", " ", subj.group(1)).strip() if subj else None}
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(r["id"], rec["v1_date"], (rec["title"] or "")[:60], flush=True)
            time.sleep(2)


def extract(pid, blob) -> dict:
    d = SRC / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "source.raw").write_bytes(blob)
    info = {"id": pid, "bytes": len(blob)}
    try:
        with tarfile.open(fileobj=__import__("io").BytesIO(blob)) as tf:
            names = [m.name for m in tf.getmembers() if m.isfile()]
            for m in tf.getmembers():
                if m.isfile() and not m.name.startswith(("/", "..")):
                    tf.extract(m, d, filter="data")
            info["kind"] = "tar"
            info["files"] = names
    except tarfile.ReadError:
        import gzip
        try:
            text = gzip.decompress(blob)
            (d / "main.tex").write_bytes(text)
            info["kind"] = "gz-single"
            info["files"] = ["main.tex"]
        except Exception as e:  # noqa: BLE001
            info["kind"] = "unreadable"
            info["error"] = repr(e)
    tex = sorted(str(p.relative_to(d)) for p in d.rglob("*.tex"))
    info["tex_files"] = tex
    info["has_documentclass"] = [t for t in tex if "\\documentclass" in (d / t).read_text(errors="replace")]
    return info


def cmd_source():
    recs = [json.loads(l) for l in (POOL / "meta.jsonl").read_text().splitlines()]
    out_path = POOL / "source.jsonl"
    done = {json.loads(l)["id"] for l in out_path.read_text().splitlines()} if out_path.exists() else set()
    SRC.mkdir(parents=True, exist_ok=True)
    with out_path.open("a") as fh:
        for r in recs:
            if r["id"] in done:
                continue
            try:
                blob = get(f"https://arxiv.org/e-print/{r['id']}", timeout=300)
                info = extract(r["id"], blob)
            except Exception as e:  # noqa: BLE001
                info = {"id": r["id"], "kind": "download_failed", "error": repr(e)}
            fh.write(json.dumps({**{k: r[k] for k in ("id", "domain", "primary")}, **info}) + "\n")
            fh.flush()
            print(r["id"], info.get("kind"), len(info.get("tex_files") or []), "tex", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    {"list": cmd_list, "meta": cmd_meta, "source": cmd_source}[sys.argv[1]]()
