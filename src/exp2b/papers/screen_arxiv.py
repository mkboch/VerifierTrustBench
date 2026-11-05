#!/usr/bin/env python3
"""Stage-1 automated paper screening for Experiment 2B (no model inference involved).

Frozen procedure (see exp2b/PAPER_SELECTION.md):
  * categories, in this order: stat.ME, q-bio.QM, physics.med-ph, eess.IV, stat.AP, cs.LG
  * listing: arXiv monthly listing 2026-09 for the category, primary-category entries only, in listing order
  * per category, iterate candidates in that order; download the arXiv source; apply automated checks:
      A1 source is a LaTeX archive with exactly one main file (\\documentclass)
      A2 all \\input/\\include resolved inside the archive
      A3 >= 2 tabular environments with numeric cells
      A4 normalised line-numbered manuscript within [7,000, 24,000] Qwen3-8B tokens
  * candidates passing A1-A4 go to stage-2 manual screening (native-edit capacity), recorded by hand
  * stop a category after the first 6 A-passing candidates
Outputs: $VTB_SOURCE_DIR/<id>/ (source), exp2b/papers/screen_stage1.jsonl
"""
import os
import io, json, re, sys, tarfile, gzip, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "exp2b"))
import normalize as N  # noqa

CATS = ["stat.ME", "q-bio.QM", "physics.med-ph", "eess.IV", "stat.AP", "cs.LG"]
WINDOW = "[202609010000 TO 202609102359]"
SRC = Path(os.environ.get("VTB_SOURCE_DIR", "sources/pilot"))
OUT = ROOT / "exp2b/papers/screen_stage1.jsonl"
MAX_PASS = 6
MAX_SCAN = 60


def get(url, tries=6):
    """HTTP GET via curl (urllib requests were refused with HTTP 406 for some source archives)."""
    import subprocess
    err = None
    for i in range(tries):
        r = subprocess.run(["curl", "-s", "-L", "--max-time", "120", "-A", "Mozilla/5.0 (compatible; VerifierTrustBench/2B)",
                            "-w", "\\n%{http_code}", url], capture_output=True)
        body, _, code = r.stdout.rpartition(b"\n")
        if r.returncode == 0 and code.strip() == b"200":
            return body
        err = RuntimeError(f"curl rc={r.returncode} http={code.strip().decode(errors='replace')}")
        time.sleep(60 * (i + 1) if code.strip() == b"429" else 5 * (i + 1))
    raise err


def listing(cat):
    """First MAX_SCAN entries of the 2026-09 monthly listing whose primary subject is `cat`, in listing (ID) order.

    The arXiv export API returned HTTP 429 for this host, so the public monthly listing page is used instead.
    """
    html = get(f"https://arxiv.org/list/{cat}/2026-09?skip=0&show=500").decode("utf-8", "replace")
    out = []
    for block in re.split(r"<dt>", html)[1:]:
        m = re.search(r'href ?="/abs/([0-9]{4}\.[0-9]{4,5})"', block)
        prim = re.search(r'primary-subject">[^<]*\(([^)]+)\)', block)
        title = re.search(r"Title:</span>\s*(.*?)\s*</div>", block, re.S)
        if not m or not prim or prim.group(1) != cat:
            continue
        out.append({"id": m.group(1), "title": re.sub(r"\s+", " ", title.group(1)) if title else None,
                    "primary": prim.group(1), "listing": f"{cat}/2026-09"})
        if len(out) >= MAX_SCAN:
            break
    return out


def fetch_source(aid):
    d = SRC / aid.replace("/", "_")
    blob = d / "eprint.bin"
    if not blob.exists():
        d.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(get(f"https://arxiv.org/src/{aid}"))
        time.sleep(3)
    return d, blob.read_bytes()


def extract(d, data):
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            for m in t.getmembers():
                if m.isfile() and m.name.endswith((".tex", ".bbl", ".sty", ".cls")):
                    files[m.name] = t.extractfile(m).read().decode("utf-8", "replace")
    except tarfile.ReadError:
        try:
            files["main.tex"] = gzip.decompress(data).decode("utf-8", "replace")
        except Exception:
            files["main.tex"] = data.decode("utf-8", "replace")
    return files


def main():
    import urllib.parse  # noqa
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B")
    done = set()
    if OUT.exists():
        done = {json.loads(l)["id"] for l in OUT.read_text().splitlines()}
    for cat in CATS:
        passed = sum(1 for l in (OUT.read_text().splitlines() if OUT.exists() else [])
                     if json.loads(l)["category"] == cat and json.loads(l)["stage1_pass"])
        for c in listing(cat):
            if passed >= MAX_PASS:
                break
            if c["id"] in done:
                continue
            rec = {"category": cat, **c, "stage1_pass": False, "reasons": []}
            try:
                d, data = fetch_source(c["id"])
                files = extract(d, data)
                mains = [k for k, v in files.items() if k.endswith(".tex") and re.search(r"^\s*\\documentclass", v, re.M)]
                if len(mains) != 1:
                    rec["reasons"].append(f"A1 main tex files: {len(mains)}")
                else:
                    text, missing = N.flatten(mains[0], files)
                    if missing:
                        rec["reasons"].append(f"A2 unresolved inputs: {missing[:5]}")
                    body = N.normalize(text)
                    numbered = N.number(body)[0]
                    ntab = len(re.findall(r"\\begin\{tabular", body))
                    numeric_tabs = len([m for m in re.finditer(r"\\begin\{tabular.*?\\end\{tabular\*?\}", body, re.S)
                                        if len(re.findall(r"\d+\.\d+", m.group(0))) >= 6])
                    ntok = len(tok(numbered)["input_ids"])
                    rec.update({"main": mains[0], "n_lines": numbered.count("\n") + 1, "qwen3_8_tokens": ntok,
                                "tabulars": ntab, "numeric_tabulars": numeric_tabs})
                    if numeric_tabs < 2:
                        rec["reasons"].append(f"A3 numeric tabulars: {numeric_tabs}")
                    if not (7000 <= ntok <= 24000):
                        rec["reasons"].append(f"A4 tokens {ntok} outside [7000, 24000]")
                    if not rec["reasons"]:
                        rec["stage1_pass"] = True
                        passed += 1
                        (d / "normalized.tex").write_text(body)
            except Exception as e:
                rec["reasons"].append(f"error {e!r}"[:300])
            with OUT.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            print(cat, c["id"], rec["stage1_pass"], rec.get("qwen3_8_tokens"), rec["reasons"], flush=True)


if __name__ == "__main__":
    main()
