#!/usr/bin/env python
"""Generate the six manuscript figures. Every value comes from FINAL_NUMBERS.json;
nothing is hand-typed into a plot."""
import json, re, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
N = json.load(open(HERE / "FINAL_NUMBERS.json"))
OUT = HERE / "figures"; OUT.mkdir(exist_ok=True)
USED = []

def v(key):
    """Numeric value of a canonical key (strips %, +, commas)."""
    USED.append(key)
    s = N[key].strip().replace(",", "").replace("%", "").lstrip("+")
    return float(s)

def frac(key):
    """(x, n) from an 'x/n' or 'x/n (p%)' canonical key."""
    USED.append(key)
    m = re.match(r"\s*(\d+)\s*/\s*(\d+)", N[key])
    return int(m.group(1)), int(m.group(2))

def txt(key):
    USED.append(key); return N[key]

plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 300, "savefig.bbox": "tight", "legend.frameon": False,
})
MODELS = ["qwen38_27", "qwen36_27", "gemma4_12", "granite42_30", "qwen3_8"]
LABEL = {"qwen38_27": "Qwen3.8-27B", "qwen36_27": "Qwen3.6-27B", "gemma4_12": "Gemma-4-12B",
         "granite42_30": "Granite-4.2-30B", "qwen3_8": "Qwen3-8B"}
C_BLIND, C_TARG, C_MID = "#B0453A", "#2F6690", "#D9A441"

def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / f"{name}.png"); fig.savefig(OUT / f"{name}.pdf")
    plt.close(fig); print("wrote", name)

# ---------------------------------------------------------------- Figure 1
# Verification is not unitary: the same relations, two information paths.
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.0), gridspec_kw={"width_ratios": [2, 1]})
blind = [v(f"h1_{m}_blind") for m in MODELS]
targ  = [v(f"h1_{m}_targ") for m in MODELS]
y = np.arange(len(MODELS))
for i, (b, t) in enumerate(zip(blind, targ)):
    ax.plot([b, t], [i, i], color="#999", lw=1, zorder=1)
ax.scatter(blind, y, color=C_BLIND, s=36, zorder=2, label="Blind discovery")
ax.scatter(targ,  y, color=C_TARG,  s=36, zorder=2, label="Relation-localized")
for i, (b, t) in enumerate(zip(blind, targ)):
    ax.annotate(f"{t-b:+.1f} pp", ((b+t)/2, i+0.22), ha="center", fontsize=7, color="#444")
ax.set_yticks(y); ax.set_yticklabels([LABEL[m] for m in MODELS]); ax.invert_yaxis()
ax.set_xlabel("Accuracy on defective relations (%)"); ax.set_xlim(0, 100)
ax.legend(loc="lower center", bbox_to_anchor=(0.45, 0.02), fontsize=7); ax.set_title("a  Same relations, two information paths")

fams = ["cross_reference", "arithmetic", "claim_evidence", "numerical", "method_result", "statistical"]
fl = [f.replace("_", "/").replace("claim/evidence", "claim–evidence") for f in fams]
d = [v(f"h1fam_{f}_diff") if f"h1fam_{f}_diff" in N else
     v(f"h1fam_{f}_targ".replace("_targ", "_targ")) for f in fams]
d = []
for f in fams:
    k = f"h1fam_{f}_diff"
    if k in N: d.append(v(k))
    else:
        x1, n1 = frac(f"h1fam_{f}_targ"); x0, n0 = frac(f"h1fam_{f}_blind")
        d.append(100*x1/n1 - 100*x0/n0)
o = np.argsort(d)
ax2.barh(np.arange(len(fams)), [d[i] for i in o], color=C_MID, height=0.6)
ax2.set_yticks(np.arange(len(fams))); ax2.set_yticklabels([fl[i] for i in o], fontsize=7)
ax2.set_xlabel("Targeted − blind (pp)"); ax2.set_title("b  Every defect family")
save(fig, "fig1_not_unitary")

# ---------------------------------------------------------------- Figure 2
# Discovery is not a ranking problem.
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.0))
ks = [1, 2, 3, 5]
for m in MODELS:
    ys = [v(f"p0_{m}_r{k}_pct") if f"p0_{m}_r{k}_pct" in N else np.nan for k in ks]
    ys = []
    for k in ks:
        kk = f"p0_{m}_r{k}_pct"
        if kk in N: ys.append(v(kk))
        else:
            x, n = frac(f"p0_{m}_r{k}"); ys.append(100*x/n)
    ax.plot(ks, ys, marker="o", ms=4, label=LABEL[m])
ax.set_xticks(ks); ax.set_xlabel("k (blind ranked list)"); ax.set_ylabel("Recall@k (%)")
ax.set_ylim(0, 100); ax.legend(fontsize=7); ax.set_title("a  Recall saturates almost immediately")

gains = [v(f"p0_{m}_gain") for m in MODELS]
ax2.bar(np.arange(len(MODELS)), gains, color=C_BLIND, width=0.6)
ax2.set_xticks(np.arange(len(MODELS)))
ax2.set_xticklabels([LABEL[m] for m in MODELS], rotation=30, ha="right", fontsize=7)
ax2.set_ylabel("Recall@5 − Recall@1 (pp)")
ax2.set_title("b  What a longer list buys")
save(fig, "fig2_discovery_vs_ranking")

# ---------------------------------------------------------------- Figure 3
# Anatomy of failure: verdict and provenance are separable.
fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4))
ax = axes[0]
crs = [v(f"p0_{m}_crs") for m in MODELS]
cu  = [v(f"p0_{m}_cu")  for m in MODELS]
irs = [v(f"p0_{m}_irs") for m in MODELS]
iu  = [v(f"p0_{m}_iu")  for m in MODELS]
tot = np.array(crs) + np.array(cu) + np.array(irs) + np.array(iu)
bottom = np.zeros(len(MODELS))
for vals, lab, col in [(crs, "correct + supported", C_TARG), (cu, "correct, unsupported", "#9DC3D4"),
                       (irs, "incorrect + supported", C_BLIND), (iu, "incorrect, unsupported", "#E2B0AA")]:
    pct = 100*np.array(vals)/tot
    ax.bar(np.arange(len(MODELS)), pct, bottom=bottom, color=col, label=lab, width=0.65)
    bottom += pct
ax.set_xticks(np.arange(len(MODELS)))
ax.set_xticklabels([LABEL[m] for m in MODELS], rotation=30, ha="right", fontsize=7)
ax.set_ylabel("% of targeted trials"); ax.set_ylim(0, 100)
ax.legend(fontsize=6, loc="upper center", bbox_to_anchor=(0.5, -0.30), ncol=2)
ax.set_title("a  Verdict × provenance")

ax = axes[1]
fa = []
for m in MODELS:
    x, n = frac(f"p0_{m}_fa"); fa.append(100*x/n)
acc = [v(f"h1_{m}_targ") for m in MODELS]
ax.scatter(acc, fa, color=C_MID, s=40)
for a, f_, m in zip(acc, fa, MODELS):
    ax.annotate(LABEL[m], (a, f_), fontsize=6, xytext=(3, 3), textcoords="offset points")
ax.set_xlabel("Targeted accuracy (%)"); ax.set_ylabel("False-alarm rate on valid relations (%)")
ax.set_title("b  Accuracy vs. specificity")

save(fig, "fig3_anatomy")

# ---------------------------------------------------------------- Figure 4
# Trajectory completion: all three states right, on the same relation.
fig, (ax0, ax, ax2) = plt.subplots(1, 3, figsize=(7.6, 3.2))
e0 = [v(f"h2_{m}_e0") for m in MODELS]
e1 = [v(f"h2_{m}_e1") for m in MODELS]
e2 = [v(f"h2_{m}_e2") for m in MODELS]
w = 0.26; xx = np.arange(len(MODELS))
ax0.bar(xx - w, e0, w, label="E0 defect", color=C_BLIND)
ax0.bar(xx,     e1, w, label="E1 valid",  color=C_TARG)
ax0.bar(xx + w, e2, w, label="E2 alternate defect", color=C_MID)
ax0.set_xticks(xx); ax0.set_xticklabels([LABEL[m] for m in MODELS], rotation=35, ha="right", fontsize=6.5)
ax0.set_ylabel("Correct (%)"); ax0.set_ylim(0, 100); ax0.legend(fontsize=6)
ax0.set_title("a  Responsiveness to the evidence")

traj = [v(f"h2_{m}_traj_pct") if f"h2_{m}_traj_pct" in N else
        100*frac(f"h2_{m}_traj")[0]/frac(f"h2_{m}_traj")[1] for m in MODELS]
single = [v(f"h2_{m}_e1") for m in MODELS]
x = np.arange(len(MODELS))
ax.bar(x - 0.18, single, 0.36, color="#C9D6DF", label="E1 alone (valid state)")
ax.bar(x + 0.18, traj,   0.36, color=C_TARG,   label="All three states correct")
ax.set_xticks(x); ax.set_xticklabels([LABEL[m] for m in MODELS], rotation=35, ha="right", fontsize=6.5)
ax.set_ylabel("%"); ax.set_ylim(0, 100); ax.legend(fontsize=6)
ax.set_title("b  One state flatters; three separate")

labels = ["MISS_DEFECT", "MISS_REVERSAL", "WRONG_EVIDENCE_BINDING", "INVALID_PROVENANCE"]
M = np.array([[v(f"tax_{m}_{l}_pct") for l in labels] for m in MODELS])
im = ax2.imshow(M, cmap="YlOrRd", vmin=0, vmax=100, aspect="auto")
ax2.set_xticks(range(len(labels)))
SHORT = {"MISS_DEFECT": "Miss\ndefect", "MISS_REVERSAL": "Miss\nreversal",
         "WRONG_EVIDENCE_BINDING": "Wrong\nbinding", "INVALID_PROVENANCE": "Invalid\nprov."}
ax2.set_xticklabels([SHORT[l] for l in labels], fontsize=6.5)
ax2.set_yticks(range(len(MODELS))); ax2.set_yticklabels([LABEL[m] for m in MODELS], fontsize=7)
for i in range(M.shape[0]):
    for j in range(M.shape[1]):
        ax2.text(j, i, f"{M[i,j]:.0f}", ha="center", va="center", fontsize=6,
                 color="white" if M[i, j] > 55 else "black")
ax2.set_title("c  Failure mode mix (%)")
fig.colorbar(im, ax=ax2, fraction=0.04)
save(fig, "fig4_trajectory")

# ---------------------------------------------------------------- Figure 5
# Search and context scope: two independent probes of the same bottleneck.
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.0))
stages = ["Direct\nblind", "Bounded\nagentic", "Relation-\nlocalized"]
vals = [v("p3_direct_pct"), v("p3_agentic_pct"), v("p3_targeted_pct")]
ax.bar(range(3), vals, color=[C_BLIND, C_MID, C_TARG], width=0.6)
for i, val in enumerate(vals):
    ax.text(i, val + 2, f"{val:.1f}%", ha="center", fontsize=8)
ax.annotate("", xy=(1, vals[1]), xytext=(0, vals[0]),
            arrowprops=dict(arrowstyle="->", color="#444", lw=1))
ax.text(0.5, vals[1] + 18, f"recovers ≈{txt('p3_recovered_pct')}\nof the deficit",
        ha="center", fontsize=7, color="#444")
ax.set_xticks(range(3)); ax.set_xticklabels(stages, fontsize=7)
ax.set_ylabel("Accuracy on defective relations (%)"); ax.set_ylim(0, 100)
ax.set_title(f"a  Bounded navigation ({txt('p3_model')}, ≤{int(v('p3_tool_budget'))} calls)")

ax2.bar([0, 1], [v("att_full_pct"), v("att_excerpt_pct")], color=[C_BLIND, C_MID], width=0.5)
for i, val in enumerate([v("att_full_pct"), v("att_excerpt_pct")]):
    ax2.text(i, val + 2, f"{val:.1f}%", ha="center", fontsize=8)
ax2.set_xticks([0, 1]); ax2.set_xticklabels(["Whole\nmanuscript", "Relation-centred\nexcerpt"], fontsize=7)
ax2.set_ylabel("Blind discovery (%)"); ax2.set_ylim(0, 100)
ax2.set_title(f"b  Context scope alone: +{v('att_delta'):.1f} pp\n(separate calibration; not pooled)")
save(fig, "fig5_search")

# ---------------------------------------------------------------- Figure 6
# What transfers between verifiers, and whether humans agree with the gold.
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.0))
arms = [("correct_rationale", "Correct rationale"), ("correct_verdict", "Correct verdict only"),
        ("cv_irrelevant", "Correct verdict +\nirrelevant text"), ("false_rationale", "False rationale"),
        ("false_verdict", "False verdict only"), ("fv_irrelevant", "False verdict +\nirrelevant text"),
        ("filler", "Length-matched filler"), ("neutral", "Neutral control")]
av = [v(f"h3arm_{a}_pct") for a, _ in arms]
o = np.argsort(av)
# colour by whether the arm carries relation-specific evidentiary content, which is the claim
RELEVANT = {"correct_rationale", "false_rationale"}
cols = [C_TARG if arms[i][0] in RELEVANT else "#B8B8B8" for i in o]
ax.barh(np.arange(len(arms)), [av[i] for i in o], color=cols, height=0.62)
ax.set_yticks(np.arange(len(arms))); ax.set_yticklabels([arms[i][1] for i in o], fontsize=6.5)
ax.set_xlabel("Downstream accuracy (%)"); ax.set_xlim(55, 85)
ax.set_title("a  Evidence content (blue), not the label")

hx, hn = frac("hv_agree"); hdx, hdn = frac("hv_def"); hcx, hcn = frac("hv_ctrl")
sx, sn = frac("hv_sens_agree"); sdx, sdn = frac("hv_sens_def")
groups = ["Overall\nagreement", "Defective\nrelations", "Valid\ncontrols"]
human = [100*hx/hn, 100*hdx/hdn, 100*hcx/hcn]
sens  = [100*sx/sn, 100*sdx/sdn, 100*hcx/hcn]
ai    = [np.nan, v("cal_def_matched_pct"), v("cal_ctrl_matched_pct")]
x = np.arange(3)
ax2.bar(x - 0.26, human, 0.24, color=C_TARG, label=f"Human (n={hn} judgments)")
ax2.bar(x,        sens,  0.24, color="#9DC3D4", label=f"Human, excl. {txt('hv_sens_item')}")
ax2.bar(x + 0.26, ai,    0.24, color=C_MID, label="Stimulus-matched AI")
for i, val in enumerate(human):
    ax2.text(i - 0.26, val + 1.5, f"{val:.1f}", ha="center", fontsize=6)
ax2.set_xticks(x); ax2.set_xticklabels(groups, fontsize=7)
ax2.set_ylabel("Agreement with deterministic label (%)"); ax2.set_ylim(0, 132)
ax2.legend(fontsize=6, loc="upper center", ncol=1)
ax2.set_title("b  Small descriptive human validation")
save(fig, "fig6_transfer_and_human")

json.dump(sorted(set(USED)), open(HERE / "FIGURE_KEYS_USED.json", "w"), indent=1)
print(f"\n{len(set(USED))} canonical keys used across 6 figures")
