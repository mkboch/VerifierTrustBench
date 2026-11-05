#!/usr/bin/env python3
"""A3: is a single scalar system ability enough, or does relative performance depend on the axis?

Three nested models, binary outcome `correct`:

  M0  UNITARY          system + axis + family + domain
  M1  UNITARY + BIAS   M0 + system x valid_state      (each system gets its own response threshold)
  M2  PROFILE          M0 + system x axis             (each system gets axis-specific strengths)

M1 matters. A system that answers "no issue" too readily scores high on the valid state (E1) and
low on every defect state, which produces a system x axis interaction without any second ability.
M1 absorbs exactly that with one extra parameter per system. The scientifically interesting
question is therefore not M2 > M0 but M2 > M1.

PRIMARY comparison: leave-one-manuscript-out held-out log loss. Case-specific difficulty is
deliberately NOT a fitted parameter, because for a genuinely held-out manuscript it is
unobservable; observable nuisance structure (defect family, domain) is included instead.

SECONDARY: in-sample likelihood-ratio tests, AIC/BIC, and a cluster-robust (manuscript) Wald test
of the interaction block.
"""
from __future__ import annotations
import csv, json, sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

warnings.simplefilter("ignore")
OUT = Path(__file__).resolve().parents[1]
SEED = 20261016
NBOOT = 10000

DATASET = sys.argv[1] if len(sys.argv) > 1 else "PROFILE_12SYSTEM_ITEMLEVEL.csv"
TAG = sys.argv[2] if len(sys.argv) > 2 else "12SYSTEM"

df = pd.read_csv(OUT / "data" / DATASET, dtype={"paper": str, "case_id": str})
df["valid_state"] = (df["axis"] == "localized_E1").astype(int)
df["correct"] = df["correct"].astype(int)

FORMULAS = {
    "M0_unitary":      "correct ~ C(system) + C(axis) + C(family) + C(domain)",
    "M1_unitary_bias": "correct ~ C(system) + C(axis) + C(family) + C(domain) + C(system):valid_state",
    "M2_profile":      "correct ~ C(system) + C(axis) + C(family) + C(domain) + C(system):C(axis)",
}

print(f"dataset {DATASET}: {len(df)} observations, {df.system.nunique()} systems, "
      f"{df.case_id.nunique()} relations, {df.paper.nunique()} manuscripts, {df.axis.nunique()} axes")


def fit(formula, data):
    return smf.glm(formula, data=data, family=sm.families.Binomial()).fit()


def design(formula, data):
    """Build each model's design matrix ONCE over the full dataset, then split by fold.

    Fitting per fold with a formula re-derives the factor coding from the training rows only,
    which fails whenever a held-out manuscript carries the only instance of a level (the
    statistical family is confined to few manuscripts). A fixed design keeps the columns aligned;
    a column that is constant within a training fold simply contributes nothing there.
    """
    import patsy
    y, X = patsy.dmatrices(formula, data, return_type="dataframe")
    return np.asarray(y).ravel(), X


def logloss(y, p, eps=1e-12):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


# ---------------------------------------------------------------- in-sample fits
insample = {}
for name, f in FORMULAS.items():
    m = fit(f, df)
    insample[name] = {"formula": f, "df_model": int(m.df_model), "n_params": int(len(m.params)),
                      "llf": float(m.llf), "aic": float(m.aic), "bic": float(m.bic),
                      "deviance": float(m.deviance)}
    print(f"{name:16} params={len(m.params):4} llf={m.llf:12.3f} AIC={m.aic:11.2f} BIC={m.bic:11.2f}")

# likelihood-ratio tests (nested)
from scipy import stats as sps
lr = {}
for a, b in (("M0_unitary", "M1_unitary_bias"), ("M1_unitary_bias", "M2_profile"), ("M0_unitary", "M2_profile")):
    d_ll = 2 * (insample[b]["llf"] - insample[a]["llf"])
    d_df = insample[b]["n_params"] - insample[a]["n_params"]
    p = float(sps.chi2.sf(d_ll, d_df)) if d_df > 0 else float("nan")
    lr[f"{a}__vs__{b}"] = {"lr_stat": d_ll, "df": d_df, "p_naive": p}
    print(f"LR {a} -> {b}: chi2={d_ll:9.2f} df={d_df:3} p(naive, ignores clustering)={p:.3e}")

# ---------------------------------------------------------------- cluster-robust Wald on the interaction
cluster_wald = {}
for name in ("M1_unitary_bias", "M2_profile"):
    m = smf.glm(FORMULAS[name], data=df, family=sm.families.Binomial()).fit(
        cov_type="cluster", cov_kwds={"groups": df["paper"]})
    terms = [t for t in m.params.index if ":" in t]
    if terms:
        R = np.zeros((len(terms), len(m.params)))
        for i, t in enumerate(terms):
            R[i, list(m.params.index).index(t)] = 1
        w = m.wald_test(R, scalar=True)
        stat = float(w.statistic)
        usable = stat >= 0 and np.isfinite(stat)
        cluster_wald[name] = {"n_interaction_terms": len(terms), "chi2": stat,
                              "p": float(w.pvalue), "usable": bool(usable),
                              "note": "" if usable else
                                      "negative/non-finite Wald statistic: the cluster-robust "
                                      "covariance is not positive semi-definite with this many "
                                      "interaction terms and only 21 manuscript clusters; the test "
                                      "is not interpretable and is reported as failed, not omitted"}
        verdict = f"p={float(w.pvalue):.3e}" if usable else "UNUSABLE (non-PSD robust covariance)"
        print(f"cluster-robust Wald on {name} interaction block: "
              f"chi2={stat:.2f} on {len(terms)} terms -> {verdict}")

# ---------------------------------------------------------------- PRIMARY: leave-one-manuscript-out
papers = sorted(df.paper.unique())
per_paper = {name: {} for name in FORMULAS}
rows_pred = []
DESIGNS = {name: design(f, df) for name, f in FORMULAS.items()}
n_fallback = 0
for pid in papers:
    mask_te = (df.paper == pid).to_numpy()
    if not mask_te.any():
        continue
    te_rows = df[mask_te]
    for name in FORMULAS:
        yv, Xv = DESIGNS[name]
        Xtr, ytr = Xv[~mask_te], yv[~mask_te]
        Xte, yte = Xv[mask_te], yv[mask_te]
        # drop columns with no variation in this training fold (they are unidentified here)
        keep = Xtr.columns[(Xtr.nunique() > 1) | (Xtr.columns == "Intercept")]
        try:
            m = sm.GLM(ytr, Xtr[keep], family=sm.families.Binomial()).fit()
            pr = np.asarray(m.predict(Xte[keep]), float)
            if not np.all(np.isfinite(pr)):
                raise ValueError("non-finite prediction")
        except Exception as e:
            pr = np.full(mask_te.sum(), ytr.mean())
            n_fallback += 1
            print(f"  [fallback to training base rate] {name} on held-out {pid}: {type(e).__name__}")
        per_paper[name][pid] = {"n": int(mask_te.sum()), "logloss": logloss(yte, pr),
                                "sum_ll": float(-logloss(yte, pr) * mask_te.sum())}
        for i, (_, r) in enumerate(te_rows.iterrows()):
            rows_pred.append({"model": name, "paper": pid, "system": r.system, "axis": r.axis,
                              "case_id": r.case_id, "correct": int(r.correct), "pred": float(pr[i])})
print(f"folds using the fallback base rate: {n_fallback} of {len(papers)*len(FORMULAS)}")

print("\nleave-one-manuscript-out held-out log loss (lower is better):")
tot = {}
for name in FORMULAS:
    n = sum(v["n"] for v in per_paper[name].values())
    ll = sum(v["sum_ll"] for v in per_paper[name].values())
    tot[name] = {"n_heldout": n, "total_log_predictive_density": ll, "mean_logloss": -ll / n}
    print(f"  {name:16} mean log loss = {-ll/n:.5f}   total lpd = {ll:11.2f}   n = {n}")

deltas = {}
for a, b in (("M0_unitary", "M1_unitary_bias"), ("M1_unitary_bias", "M2_profile"), ("M0_unitary", "M2_profile")):
    d = tot[a]["mean_logloss"] - tot[b]["mean_logloss"]
    deltas[f"{a}__to__{b}"] = d
    print(f"  improvement {a} -> {b}: {d:+.5f} log loss per observation "
          f"({'better' if d > 0 else 'WORSE'})")

# ---------------------------------------------------------------- bootstrap over manuscripts
rng = np.random.default_rng(SEED)
used = [p for p in papers if p in per_paper["M0_unitary"]]
pp = {name: np.array([per_paper[name][p]["sum_ll"] for p in used]) for name in FORMULAS}
nn = np.array([per_paper["M0_unitary"][p]["n"] for p in used])
boot = {k: [] for k in deltas}
for _ in range(NBOOT):
    idx = rng.integers(0, len(used), len(used))
    n_b = nn[idx].sum()
    ml = {name: -pp[name][idx].sum() / n_b for name in FORMULAS}
    for a, b in (("M0_unitary", "M1_unitary_bias"), ("M1_unitary_bias", "M2_profile"),
                 ("M0_unitary", "M2_profile")):
        boot[f"{a}__to__{b}"].append(ml[a] - ml[b])

print(f"\nmanuscript-cluster bootstrap ({NBOOT} draws over {len(used)} contributing manuscripts, seed {SEED}):")
ci = {}
for k, v in boot.items():
    v = np.array(v)
    lo, hi = np.percentile(v, [2.5, 97.5])
    frac = float((v > 0).mean())
    ci[k] = {"point": deltas[k], "lo": float(lo), "hi": float(hi), "p_better": frac}
    print(f"  {k:36} {deltas[k]:+.5f}  95% CI [{lo:+.5f}, {hi:+.5f}]  "
          f"improves in {100*frac:.1f}% of resamples")

json.dump({"dataset": DATASET, "tag": TAG, "seed": SEED, "n_bootstrap": NBOOT,
           "n_obs": int(len(df)), "n_systems": int(df.system.nunique()),
           "n_relations": int(df.case_id.nunique()), "n_manuscripts": int(df.paper.nunique()),
           "formulas": FORMULAS, "insample": insample, "likelihood_ratio": lr,
           "cluster_robust_wald": cluster_wald, "lomo": tot, "lomo_deltas": deltas,
           "lomo_bootstrap_ci": ci,
           "per_manuscript": {n: per_paper[n] for n in FORMULAS}},
          (OUT / f"data/UNITARY_VS_PROFILE_{TAG}.json").open("w"), indent=1)
pd.DataFrame(rows_pred).to_csv(OUT / f"data/UNITARY_VS_PROFILE_PREDICTIONS_{TAG}.csv", index=False)
print(f"\nwrote UNITARY_VS_PROFILE_{TAG}.json and predictions CSV")
