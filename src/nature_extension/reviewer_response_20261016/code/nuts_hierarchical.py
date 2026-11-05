#!/usr/bin/env python3
"""C3: refit the hierarchical blind-vs-localized model with NUTS instead of variational inference.

The manuscript currently reports a Bayesian mixed GLM fitted by VI. VI understates posterior
uncertainty in hierarchical logistic models, which is exactly the wrong failure mode for a
headline claim. This refits the same structure with proper MCMC and reports convergence
diagnostics. If it does not converge, that is reported and the VI model is dropped from headline
evidence rather than patched.

Model (population-averaged contrast with nested random intercepts):

  y_i ~ Bernoulli(p_i)
  logit(p_i) = a + b * localized_i + u_manuscript[i] + v_relation[i] + s_system[i]
  u ~ N(0, sigma_m), v ~ N(0, sigma_r), s ~ N(0, sigma_s)

b is the log-odds of being correct under relation-localized verification relative to blind
discovery, holding manuscript, relation and system.
"""
from __future__ import annotations
import csv, json, collections
from pathlib import Path
import numpy as np

OUT = Path(__file__).resolve().parents[1]
SEED = 20261016

rows = [r for r in csv.DictReader((OUT / "data/PROFILE_5SYSTEM_184_ITEMLEVEL.csv").open())
        if r["axis"] in ("blind_E0", "localized_E0")]
for r in rows:
    r["correct"] = int(r["correct"])
print(f"observations: {len(rows)}")

papers = sorted({r["paper"] for r in rows})
rels = sorted({r["case_id"] for r in rows})
systems = sorted({r["system"] for r in rows})
pi = {p: i for i, p in enumerate(papers)}
ri = {c: i for i, c in enumerate(rels)}
si = {s: i for i, s in enumerate(systems)}

y = np.array([r["correct"] for r in rows], dtype="int64")
loc = np.array([r["axis"] == "localized_E0" for r in rows], dtype="float64")
mi = np.array([pi[r["paper"]] for r in rows])
rr = np.array([ri[r["case_id"]] for r in rows])
ss = np.array([si[r["system"]] for r in rows])
print(f"{len(papers)} manuscripts, {len(rels)} relations, {len(systems)} systems")

try:
    import pymc as pm
    import arviz as az
except ImportError as e:
    json.dump({"status": "UNAVAILABLE", "reason": str(e)},
              (OUT / "data/NUTS_HIERARCHICAL.json").open("w"), indent=1)
    raise SystemExit(f"pymc unavailable: {e}")

with pm.Model() as model:
    a = pm.Normal("intercept", 0.0, 2.5)
    b = pm.Normal("localized_effect", 0.0, 2.5)
    sm = pm.HalfNormal("sigma_manuscript", 1.0)
    sr = pm.HalfNormal("sigma_relation", 1.0)
    sy = pm.HalfNormal("sigma_system", 1.0)
    u = pm.Normal("u_manuscript", 0.0, sm, shape=len(papers))
    v = pm.Normal("v_relation", 0.0, sr, shape=len(rels))
    s = pm.Normal("s_system", 0.0, sy, shape=len(systems))
    eta = a + b * loc + u[mi] + v[rr] + s[ss]
    pm.Bernoulli("obs", logit_p=eta, observed=y)
    idata = pm.sample(draws=2000, tune=2000, chains=4, cores=4, target_accept=0.95,
                      random_seed=SEED, progressbar=False, idata_kwargs={"log_likelihood": False})
    idata.extend(pm.sample_posterior_predictive(idata, random_seed=SEED, progressbar=False))

summ = az.summary(idata, var_names=["intercept", "localized_effect", "sigma_manuscript",
                                    "sigma_relation", "sigma_system"], round_to=4)
print("\n", summ.to_string())

div = int(idata.sample_stats["diverging"].sum())
rhat_max = float(az.rhat(idata).max().to_array().max())
ess_min = float(az.ess(idata).min().to_array().min())
print(f"\ndivergences: {div}")
print(f"max R-hat: {rhat_max:.4f}")
print(f"min bulk ESS: {ess_min:.0f}")

post = idata.posterior["localized_effect"].values.ravel()
or_ = np.exp(post)
hdi = az.hdi(post, hdi_prob=0.95)

# posterior predictive check: observed vs predicted rate in each condition
ppc = idata.posterior_predictive["obs"].values.reshape(-1, len(y))
obs_rate = {"blind": float(y[loc == 0].mean()), "localized": float(y[loc == 1].mean())}
pp_rate = {"blind": ppc[:, loc == 0].mean(axis=1), "localized": ppc[:, loc == 1].mean(axis=1)}
print("\nposterior predictive check (observed vs 95% predictive interval):")
for k in ("blind", "localized"):
    lo, hi = np.percentile(pp_rate[k], [2.5, 97.5])
    inside = lo <= obs_rate[k] <= hi
    print(f"  {k:10} observed {100*obs_rate[k]:5.1f}%  predicted [{100*lo:5.1f}, {100*hi:5.1f}]  "
          f"{'ok' if inside else 'MISCALIBRATED'}")

converged = div == 0 and rhat_max < 1.01 and ess_min > 400
out = {
    "status": "CONVERGED" if converged else "CONVERGENCE_PROBLEM",
    "sampler": "NUTS (pymc)", "chains": 4, "tune": 2000, "draws_per_chain": 2000,
    "total_draws": 8000, "target_accept": 0.95, "seed": SEED,
    "divergences": div, "max_rhat": rhat_max, "min_ess": ess_min,
    "localized_effect_log_odds": {"mean": float(post.mean()), "sd": float(post.std()),
                                  "hdi_2.5": float(hdi[0]), "hdi_97.5": float(hdi[1])},
    "localized_odds_ratio": {"mean": float(or_.mean()), "median": float(np.median(or_)),
                             "hdi_2.5": float(np.exp(hdi[0])), "hdi_97.5": float(np.exp(hdi[1]))},
    "variance_components": {k: {"mean": float(summ.loc[k, "mean"]),
                                "hdi_3%": float(summ.loc[k, "hdi_3%"]),
                                "hdi_97%": float(summ.loc[k, "hdi_97%"])}
                            for k in ("sigma_manuscript", "sigma_relation", "sigma_system")},
    "posterior_predictive_check": {
        k: {"observed": obs_rate[k],
            "pred_lo": float(np.percentile(pp_rate[k], 2.5)),
            "pred_hi": float(np.percentile(pp_rate[k], 97.5))} for k in obs_rate},
    "n_obs": int(len(y)), "n_manuscripts": len(papers), "n_relations": len(rels),
    "n_systems": len(systems),
}
json.dump(out, (OUT / "data/NUTS_HIERARCHICAL.json").open("w"), indent=1)
print(f"\nSTATUS: {out['status']}")
print(f"localized effect: log-odds {post.mean():.3f} [{hdi[0]:.3f}, {hdi[1]:.3f}], "
      f"OR {np.exp(post.mean()):.2f} [{np.exp(hdi[0]):.2f}, {np.exp(hdi[1]):.2f}]")
print("wrote data/NUTS_HIERARCHICAL.json")
