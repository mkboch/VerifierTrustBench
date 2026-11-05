#!/usr/bin/env python3
"""Denominators, multiplicity (BH FDR), GEE vs Bayes, funnel. Appends to the reanalysis body."""
import json, sys
from collections import Counter
from decimal import Decimal, getcontext
from math import comb, exp
from pathlib import Path
getcontext().prec=60
ROOT=Path(__file__).resolve().parents[2]
O=json.load(open(ROOT/'runs/exp3heldout_latest/analysis.json'))
def ep(b,c):
    n=b+c
    if n==0: return Decimal(1)
    k=min(b,c)
    return min(2*sum(Decimal(comb(n,i)) for i in range(k+1))/(Decimal(2)**n),Decimal(1))
def pdisp(p):
    return "p < 1e-50" if p<Decimal('1e-50') else (f"p < 1e-10" if p<Decimal('1e-10') else f"p = {float(p):.4g}")
def bh(pairs):
    """Benjamini-Hochberg q-values. pairs: [(label, Decimal p)] -> [(label,p,q)] in input order."""
    n=len(pairs); order=sorted(range(n), key=lambda i: pairs[i][1])
    q=[None]*n; prev=Decimal(1)
    for rank,i in enumerate(reversed(order),start=1):
        idx=n-rank+1
        val=min(prev, pairs[i][1]*n/idx)
        q[i]=val; prev=val
    return [(pairs[i][0],pairs[i][1],q[i]) for i in range(n)]

L=[];w=L.append
w("## 9. Denominator reconciliation\n")
p2=O['h2']['pooled']; h1=O['h1']['pooled']
w("Denominators differ across reported quantities because each requires a different set of trials to have "
  "returned a **valid** response, and technical failures are not imputed. With 184 cases x 5 primary models "
  "there are 920 potential model-case units per state.\n")
w("| Quantity | Denominator | Requires |")
w("|---|---|---|")
w(f"| E0 detection | {p2['E0_detection']['n']} | a valid targeted response in state E0 |")
w(f"| E1 clearance | {p2['E1_clearance']['n']} | a valid targeted response in state E1 |")
w(f"| E2 detection | {p2['E2_detection']['n']} | a valid targeted response in state E2 |")
w(f"| Full trajectory | {p2['trajectory']['n']} | valid responses in **all three** states simultaneously |")
w(f"| H1 paired units | {h1['n']} | a valid **targeted E0** response **and** a valid **blind E0** response |")
w("")
w(f"Of 920 potential units per state, E0 lost {920-p2['E0_detection']['n']}, E1 lost {920-p2['E1_clearance']['n']} "
  f"and E2 lost {920-p2['E2_detection']['n']} to technical failure (truncation or parse failure). The trajectory "
  f"denominator ({p2['trajectory']['n']}) is smaller than any single state because it requires the conjunction of "
  "three valid responses: a single failure in any state removes that case from the trajectory. The H1 denominator "
  f"({h1['n']}) is a different conjunction — targeted E0 **and** blind E0 — so it is not nested within the "
  "trajectory denominator and the two need not coincide. All four are reported as observed; **no missing response "
  "was imputed, and no case was dropped for any reason other than a technical failure.**\n")

w("## 10. Subgroup multiplicity (Benjamini-Hochberg)\n")
w("The preregistered **pooled** H1 test remains the primary inferential result and is **not** adjusted. Every "
  "stratified test below is a *robustness / heterogeneity* analysis. We report BH FDR-adjusted q-values within "
  "each subgroup family so that subgroup significance is not read as independent confirmation.\n")
for fam,lbl in (('by_model','Per-model'),('by_domain','Per-domain'),('by_family','Per-defect-family')):
    d=O['h1'][fam]
    pairs=[(k, ep(v['first_only'],v['second_only'])) for k,v in d.items()]
    res=bh(pairs)
    w(f"### {lbl} (family size {len(pairs)})\n")
    w("| Subgroup | Effect (pp) | Raw p | BH q | Significant at q<0.05 |")
    w("|---|---|---|---|---|")
    for (k,p,q) in res:
        v=d[k]
        w(f"| {k} | {100*v['diff']:+.1f} | {pdisp(p)} | {pdisp(q)} | {'yes' if q<Decimal('0.05') else '**no**'} |")
    w("")
d=O['h1']['by_family']
pairs=[(k, ep(v['first_only'],v['second_only'])) for k,v in d.items()]
res=bh(pairs)
nsig=[k for k,p,q in res if q>=Decimal('0.05')]
w(f"After BH adjustment within the six-family set, the families that remain non-significant are: "
  f"{', '.join(nsig) if nsig else 'none'}. This does not change the pooled result, and the pooled result is not "
  "an average of these subgroups.\n")
w("**The leave-one-out analyses are not multiplicity-corrected and must not be**: they are 32 overlapping "
  "recomputations of the *same* pooled estimate on nested subsets, not 32 independent hypotheses. They are "
  "reported as a stability check on a single effect, and the relevant summary is that the estimate never leaves "
  "its range and never reverses sign.\n")

w("## 11. GEE versus Bayesian mixed model\n")
g=O['hierarchical']['gee_cluster_paper']; b=O['hierarchical']['bayes_mixed_glm']
w(f"| Model | Estimand | Odds ratio | 95% interval |")
w("|---|---|---|---|")
w(f"| GEE logistic, exchangeable, clustered by manuscript | **population-averaged (marginal)** | "
  f"{g['blind_odds_ratio']:.4f} | [{g['blind_or_ci95'][0]:.4f}, {g['blind_or_ci95'][1]:.4f}] |")
w(f"| Bayesian mixed GLM, random intercepts for manuscript and case | **cluster-conditional (subject-specific)** | "
  f"{b['blind_odds_ratio']:.4f} | [{b['blind_or_ci95'][0]:.4f}, {b['blind_or_ci95'][1]:.4f}] |")
w("")
w("**These two odds ratios estimate different quantities and are not expected to be numerically equal.** For a "
  "logistic link the marginal (population-averaged) effect is attenuated toward 1 relative to the "
  "cluster-conditional effect whenever there is non-zero between-cluster variance — the well-known "
  "non-collapsibility of the odds ratio. The conditional estimate answers *how the odds change for a given "
  "manuscript and case*; the marginal estimate answers *how the odds change averaged over the population of "
  "manuscripts*. Observing a conditional OR further from 1 than the marginal OR "
  f"({b['blind_odds_ratio']:.3f} versus {g['blind_odds_ratio']:.3f}) is the expected direction, not a "
  "discrepancy.\n")
vc=b['random_effect_sd']
w(f"Variance components are stored on a **log-SD scale** by statsmodels: the raw values "
  f"({vc['paper']:.4f} for manuscript, {vc['case']:.4f} for case) imply standard deviations of "
  f"{exp(vc['paper']):.4f} and {exp(vc['case']):.4f}. Between-case heterogeneity therefore exceeds "
  f"between-manuscript heterogeneity by roughly {exp(vc['case'])/exp(vc['paper']):.1f}x, consistent with "
  "difficulty being a property of the individual relation rather than of the paper. The Bayesian fit is "
  "variational, so its interval is an approximation and is narrower than the GEE interval; that is a property of "
  "mean-field variational inference, **not** evidence of a stronger effect.\n")
w("**Neither hierarchical model replaces the paired counts.** Both are reported alongside them.\n")

w("## 12. P-value display convention\n")
w("Manuscript-facing text uses threshold notation for very small values (e.g. `p < 1e-50`). Exact values computed "
  "in exact rational arithmetic are retained in machine-readable artifacts. Stored float `0.0` values in "
  "`analysis.json` are IEEE-754 underflow and are never quoted as zero. The pooled H1 exact value is "
  f"{ep(h1['first_only'],h1['second_only']):.3E}, displayed as {pdisp(ep(h1['first_only'],h1['second_only']))}.\n")
Path(ROOT/'nature_extension/phase0_methods/_reanalysis_body2.md').write_text("\n".join(L)+"\n")
print("generated part 2:", len(L), "lines")
