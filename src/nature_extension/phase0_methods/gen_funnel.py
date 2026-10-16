#!/usr/bin/env python3
"""Phase 0B: reproducible screening funnel from frozen artifacts. Emits CSV, MD and a figure-ready SVG."""
import csv, json, statistics as st
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'nature_extension/phase0_methods'
rows=list(csv.DictReader(open(ROOT/'exp3heldout/PAPER_CANDIDATE_POOL.csv')))
sel=json.load(open(ROOT/'exp3heldout/selection.json'))
screen=[json.loads(l) for l in open(ROOT/'exp3heldout/pool/screen.jsonl')]

n_screened=len(rows)
n_screenpass=sum(1 for r in screen if r['eligible'])
n_eligible=sum(1 for r in rows if r['eligible']=='True')
n_selected=len(sel['selected'])

# frozen exclusion reasons -> grouped categories
GROUP={'source_unavailable':'source unavailable','main_files':'malformed source (multiple/ambiguous main file)',
 'unresolved_inputs':'inaccessible dependency / unresolved input','unbalanced_envs':'malformed source (unbalanced environments)',
 'too_few_lines':'insufficient quantitative content','few_numeric_tables':'insufficient quantitative content',
 'few_decimals':'insufficient quantitative content','no_pct_or_stats':'insufficient quantitative content',
 'few_refs':'insufficient quantitative content','tokens_out_of_band':'context band (overflow or too short)',
 'outside_window':'outside frozen publication window','cases':'no sufficient mechanically checkable relation',
 'families':'no sufficient mechanically checkable relation','not_mined':'failed content screen (not mined)'}
per_reason=Counter(); grouped=Counter()
for r in rows:
    if r['eligible']=='True': continue
    for part in r['exclusion_reason'].split(';'):
        k=part.split('(')[0].split('=')[0]
        if k:
            per_reason[k]+=1; grouped[GROUP.get(k,'other frozen eligibility reason')]+=1

def num(v):
    try: return float(v)
    except Exception: return None
def stats(subset, field):
    vals=[num(r[field]) for r in subset]; vals=[v for v in vals if v is not None]
    return (st.median(vals), min(vals), max(vals), len(vals)) if vals else (None,)*4

elig=[r for r in rows if r['eligible']=='True']
selids={s['id'] for s in sel['selected']}
selrows=[r for r in rows if r['id'] in selids]

with open(OUT/'SCREENING_FUNNEL.csv','w',newline='') as fh:
    wr=csv.writer(fh)
    wr.writerow(['stage','n','note'])
    wr.writerow(['candidates_retrieved_and_screened',n_screened,'arXiv listings, frozen window and categories'])
    wr.writerow(['passed_content_screen',n_screenpass,'prepare_screen.py data-only criteria'])
    wr.writerow(['eligible',n_eligible,'content screen AND window AND >=8 validated cases spanning >=3 families'])
    wr.writerow(['selected',n_selected,'seeded stratified selection with author disjointness'])
    wr.writerow([])
    wr.writerow(['exclusion_category','n_manuscripts_failing','note'])
    for k,v in grouped.most_common(): wr.writerow([k,v,'manuscripts may fail several criteria'])
    wr.writerow([])
    wr.writerow(['raw_frozen_reason','n_manuscripts_failing',''])
    for k,v in per_reason.most_common(): wr.writerow([k,v,''])

L=[];w=L.append
w("# Phase 0B — manuscript screening funnel\n")
w("Reproducible from frozen artifacts only (`exp3heldout/PAPER_CANDIDATE_POOL.csv`, `pool/screen.jsonl`, "
  "`selection.json`). Regenerate with `python nature_extension/phase0_methods/gen_funnel.py`.\n")
w("## Funnel\n")
w("| Stage | n | Retained | Criterion |")
w("|---|---|---|---|")
w(f"| Candidates retrieved and screened | {n_screened} | — | arXiv listings within the frozen window and category map |")
w(f"| Passed data-only content screen | {n_screenpass} | {100*n_screenpass/n_screened:.1f}% | single resolvable LaTeX source; >=250 lines; token band; >=2 numeric tables; >=40 distinct decimals; >=5 resolvable cross-references; >=1 percentage or p-value; balanced environments |")
w(f"| Eligible | {n_eligible} | {100*n_eligible/n_screened:.1f}% | content screen **and** v1 date in window **and** >=8 mechanically validated cases spanning >=3 defect families |")
w(f"| Selected | {n_selected} | {100*n_selected/n_screened:.1f}% | seeded stratified selection, author-disjoint, {sel['target_per_domain']} per domain + declared case-count top-up |")
w("")
w("## Exclusions by category\n")
w("A manuscript can fail several criteria; counts are per criterion over the "
  f"{n_screened - n_eligible} excluded manuscripts and therefore sum to more than that total.\n")
w("| Exclusion category | Manuscripts failing |")
w("|---|---|")
for k,v in grouped.most_common(): w(f"| {k} | {v} |")
w("")
w("### Raw frozen reason codes\n")
w("| Reason code | n |")
w("|---|---|")
for k,v in per_reason.most_common(): w(f"| `{k}` | {v} |")
w("")
w("## Eligible pool versus screened pool (available metadata only)\n")
w("| Metric | Screened pool | Eligible (n=%d) | Selected (n=%d) |" % (n_eligible,n_selected))
w("|---|---|---|---|")
for field,label in (('tokens_qwen3_8b','Tokens (Qwen3-8B), median [min, max]'),
                    ('lines','Numbered lines, median [min, max]'),
                    ('numeric_tabulars','Numeric tables, median [min, max]'),
                    ('decimals','Distinct decimals, median [min, max]'),
                    ('resolvable_refs','Resolvable cross-references, median [min, max]')):
    a=stats(rows,field); b=stats(elig,field); c=stats(selrows,field)
    f=lambda t: f"{t[0]:.0f} [{t[1]:.0f}, {t[2]:.0f}]" if t[0] is not None else "n/a"
    w(f"| {label} | {f(a)} | {f(b)} | {f(c)} |")
w("")
w("Eligible manuscripts are, by construction, the quantitatively densest end of the screened pool: the screen "
  "selects for numeric tables, decimals and resolvable cross-references, and eligibility additionally requires "
  "that a deterministic checker could validate at least eight native relations.\n")
w("## The eligibility fraction is a construct boundary, not a sampling accident\n")
w(f"Only **{n_eligible} of {n_screened} manuscripts ({100*n_eligible/n_screened:.1f}%)** were eligible. This is "
  "the clearest quantitative statement of the study's construct boundary. It does **not** mean that "
  f"{100*(1-n_eligible/n_screened):.1f}% of science is unverifiable; it means that only a small minority of "
  "manuscripts contain relations that a **deterministic checker can re-derive from the text alone** at the "
  "density required to build a per-paper case set. The dominant exclusion reasons are insufficient quantitative "
  "content and unavailable or malformed source, not scientific quality.\n")
w("Two consequences must travel with every claim built on this corpus:\n")
w("1. The corpus is **not representative of scientific manuscripts in general**; it is representative of "
  "quantitatively dense manuscripts with machine-checkable internal relations.\n")
w("2. The mechanical-gold guarantee is purchased **precisely by** this narrowing. Broadening the construct would "
  "require abandoning deterministic gold or accepting model-generated ground truth.\n")
Path(OUT/'SCREENING_FUNNEL.md').write_text("\n".join(L)+"\n")

# ---- figure-ready SVG
W,H=760,430
bars=[("Screened",n_screened),("Content screen",n_screenpass),("Eligible",n_eligible),("Selected",n_selected)]
mx=max(v for _,v in bars); x0,y0,bw,gap=170,60,470,80
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica,Arial,sans-serif">',
     f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
     f'<text x="24" y="34" font-size="17" font-weight="600" fill="#111">Manuscript screening funnel</text>']
cols=["#2b6cb0","#3182ce","#63b3ed","#1a365d"]
for i,(lbl,v) in enumerate(bars):
    y=y0+i*gap; wpx=max(3,bw*v/mx)
    svg.append(f'<rect x="{x0}" y="{y}" width="{wpx:.1f}" height="46" fill="{cols[i]}" rx="3"/>')
    svg.append(f'<text x="{x0-12}" y="{y+29}" font-size="13" text-anchor="end" fill="#222">{lbl}</text>')
    svg.append(f'<text x="{x0+wpx+10:.1f}" y="{y+29}" font-size="13" fill="#111">{v}  ({100*v/n_screened:.1f}%)</text>')
svg.append(f'<text x="24" y="{H-22}" font-size="11.5" fill="#555">Eligibility requires deterministic checkability '
           f'of >=8 native relations: a construct boundary, not a quality judgement.</text>')
svg.append('</svg>')
Path(OUT/'SCREENING_FUNNEL.svg').write_text("\n".join(svg)+"\n")
print(f"funnel: {n_screened} -> {n_screenpass} -> {n_eligible} -> {n_selected}")
print("wrote SCREENING_FUNNEL.{csv,md,svg}")
