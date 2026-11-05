#!/usr/bin/env python3
"""Phase 1 follow-up harvester for statistical-consistency enrichment.

FOLLOW-UP EXPERIMENT. Does not modify exp3heldout/harvest.py (frozen) and does not touch the Experiment 3 pool.

Frozen acquisition principles, declared BEFORE any mining or inference:
  * SAME publication window as Experiment 3 (2026-07-01 .. 2026-09-15). The window is NOT changed.
  * SAME domain->category map. We scan DEEPER in the same monthly listings than Experiment 3 did (which capped
    each category), so every candidate is a paper Experiment 3 never reached.
  * Categories restricted to the DEMONSTRATED-YIELD domains for this relation family (C_biomedical,
    B_vision_signal). This is a relation-density decision taken from CORPUS statistics only -- no model output was
    consulted. Statistics-methodology categories are excluded because they yielded ZERO statistical cases across
    29 screened Experiment 3 papers.
  * Any arXiv id already in the Experiment 3 listing/screen pools or excluded list is skipped.
  * Sources go to $VTB_SOURCE_DIR (LaTeX only, small). A shared read-only mount is not writable by
    this account; /home is at 98%.

    python harvest_stat.py list [--cap N]
    python harvest_stat.py source
"""
from __future__ import annotations
import os
import argparse, gzip, io, json, re, sys, tarfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "exp3heldout"))
import harvest as H                     # frozen; imported read-only

HERE = Path(__file__).resolve().parent
POOL = HERE / "pool"
SRC = Path(os.environ.get("VTB_SOURCE_DIR", "sources/statistical_enrichment"))
CATS = {"C_biomedical": ["physics.med-ph", "q-bio.QM", "q-bio.NC", "q-bio.PE", "q-bio.TO"],
        "B_vision_signal": ["eess.IV", "eess.SP", "cs.CV"]}
MONTHS = H.MONTHS


def existing_ids() -> set[str]:
    ids = set(H.EXCLUDED_IDS)
    for rel in ("exp3heldout/pool/listing.jsonl", "exp3heldout/pool/screen.jsonl"):
        p = ROOT / rel
        if p.exists():
            ids |= {json.loads(l)["id"] for l in p.read_text().splitlines() if l.strip()}
    return ids


def cmd_list(cap: int):
    POOL.mkdir(parents=True, exist_ok=True)
    out = POOL / "listing.jsonl"
    seen = {json.loads(l)["id"] for l in out.read_text().splitlines()} if out.exists() else set()
    prior = existing_ids()
    print(f"skipping {len(prior)} ids already known to Experiment 3", flush=True)
    with out.open("a") as fh:
        for domain, cats in CATS.items():
            for cat in cats:
                n = 0
                for month in MONTHS:
                    for skip in (0, 500, 1000, 1500, 2000):
                        if n >= cap:
                            break
                        try:
                            html = H.get(f"https://arxiv.org/list/{cat}/{month}?skip={skip}&show=500"
                                         ).decode("utf-8", "replace")
                        except Exception as e:  # noqa: BLE001
                            print("LIST FAIL", cat, month, skip, e, flush=True); continue
                        got = 0
                        for block in re.split(r"<dt>", html)[1:]:
                            if n >= cap:
                                break
                            m = re.search(r'href ?="/abs/([0-9]{4}\.[0-9]{4,5})"', block)
                            prim = re.search(r'primary-subject">[^<]*\(([^)]+)\)', block)
                            title = re.search(r"Title:</span>\s*(.*?)\s*</div>", block, re.S)
                            if not m or not prim or prim.group(1) != cat:
                                continue
                            pid = m.group(1)
                            if pid in seen or pid in prior:
                                continue
                            seen.add(pid); n += 1; got += 1
                            fh.write(json.dumps({"id": pid,
                                                 "title": re.sub(r"\s+", " ", title.group(1)) if title else None,
                                                 "primary": cat, "domain": domain,
                                                 "listing_month": month, "skip": skip}) + "\n")
                            fh.flush()
                        time.sleep(2)
                        if got == 0:
                            break
                print(f"{domain} {cat}: {n} new candidates", flush=True)


def _fetch(pid, dest):
    raw = H.get(f"https://arxiv.org/e-print/{pid}")
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
            tf.extractall(dest, filter="data")
    except tarfile.ReadError:
        (dest / "main.tex").write_bytes(gzip.decompress(raw))


def cmd_source():
    SRC.mkdir(parents=True, exist_ok=True)
    recs = [json.loads(l) for l in (POOL / "listing.jsonl").read_text().splitlines() if l.strip()]
    ok = fail = skip = 0
    for i, r in enumerate(recs, 1):
        d = SRC / r["id"]
        if d.exists() and any(d.iterdir()):
            skip += 1; continue
        try:
            _fetch(r["id"], d); ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            if fail <= 10:
                print(f"  source fail {r['id']}: {e}", flush=True)
        if i % 50 == 0:
            print(f"  {i}/{len(recs)} ok={ok} skip={skip} fail={fail}", flush=True)
        time.sleep(1)
    print(f"sources: ok={ok} skip={skip} fail={fail} -> {SRC}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["list", "source"])
    ap.add_argument("--cap", type=int, default=140)
    a = ap.parse_args()
    (cmd_list(a.cap) if a.cmd == "list" else cmd_source())
