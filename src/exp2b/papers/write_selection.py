#!/usr/bin/env python3
"""Render exp2b/PAPER_SELECTION.md from the stage-1 and stage-2 screening records (no model output involved)."""
import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S1 = [json.loads(l) for l in (ROOT / "exp2b/papers/screen_stage1.jsonl").read_text().splitlines()]
S2 = [json.loads(l) for l in (ROOT / "exp2b/papers/screen_stage2.jsonl").read_text().splitlines()]
CATS = ["stat.ME", "q-bio.QM", "physics.med-ph", "eess.IV", "stat.AP", "cs.LG"]
selected = [r for r in S2 if r["selected"]]
L = ["# Experiment 2B — manuscript selection", "",
     "Selection used only public arXiv metadata and LaTeX sources; no verifier model saw any candidate before the selection was "
     "frozen, and no paper was kept or dropped on the basis of model behaviour.", "",
     "## Procedure (fixed in advance)", "",
     "1. **Listing.** For each category in the order stat.ME, q-bio.QM, physics.med-ph, eess.IV, stat.AP, cs.LG, the arXiv monthly "
     "listing for 2026-09 (primary-category entries only, listing order). The arXiv export API returned HTTP 429 from this host, so "
     "the public listing page was used. Recent (September 2026) papers postdate the release of the verifier models.",
     "2. **Stage 1 (automatic; `exp2b/papers/screen_arxiv.py`).** A1 LaTeX source with exactly one main file; A2 all \\\\input "
     "resolved; A3 at least two tabulars with numeric cells; A4 the standardised line-numbered manuscript is 7,000-24,000 Qwen3-8B "
     "tokens. A category stops after six stage-1 passes. Download failures are not exclusions: an early urllib downloader received "
     "spurious HTTP 406 responses for some sources; those candidates were re-screened with curl (`screen_errors_406.json`).",
     "3. **Stage 2 (manual; `exp2b/papers/STAGE2_CRITERIA.md`, hashed before the second candidate was read).** Stage-1 passes are "
     "read in listing order; the first meeting S2a-S2e is selected and later candidates in that category are not read.",
     "4. **Standardisation (`exp2b/normalize.py`).** Document body only; comments, author/affiliation/contact metadata, author "
     "contributions, funding/availability/disclosure sections and the reference list removed; prose paragraphs on single lines; "
     "table and equation rows kept one per line. Scientific content unchanged.",
     "5. **Context gate (`exp2b/context_gate.py`).** Actual tokenizer counts of the chat-templated blind request and the longest "
     "targeted request for every primary model must leave max_tokens + 256 within 32,768 (`CONTEXT_GATE.json`).", "",
     "## Selected papers", "", "| Category | arXiv | Title | Stage-1 tokens | Stage-2 note |", "|---|---|---|---|---|"]
s1 = {r["id"]: r for r in S1}
for r in selected:
    L.append(f"| {r['category']} | {r['id']} | {s1.get(r['id'], {}).get('title')} | {s1.get(r['id'], {}).get('qwen3_8_tokens')} | {r['reason']} |")
L += ["", "## Stage-2 exclusions", ""]
for r in S2:
    if not r["selected"]:
        L.append(f"- {r['category']} {r['id']} ({s1.get(r['id'], {}).get('title')}): failed {', '.join(r['criteria_failed'])} — {r['reason']}")
L += ["", "## Stage-1 screening record", ""]
for cat in CATS:
    rows = [r for r in S1 if r["category"] == cat]
    if not rows:
        continue
    sel = [r["id"] for r in selected if r["category"] == cat]
    L += [f"### {cat} — {len(rows)} candidates screened, {sum(r['stage1_pass'] for r in rows)} stage-1 passes" + (f"; selected {sel[0]}" if sel else ""), "",
          "| arXiv | Stage 1 | Tokens | Reason |", "|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['id']} | {'pass' if r['stage1_pass'] else 'fail'} | {r.get('qwen3_8_tokens') or '—'} | {'; '.join(r['reasons']) or '—'} |")
    L.append("")
(ROOT / "exp2b/PAPER_SELECTION.md").write_text("\n".join(L) + "\n")
print("wrote PAPER_SELECTION.md;", len(selected), "selected")
