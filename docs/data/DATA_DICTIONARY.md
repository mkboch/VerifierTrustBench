# Public research data — dictionary

Seven files. Together they are enough to reproduce the study's published numerical
results; apart, each says what it is and what it is not.

**An E0 defect is a perturbation this study injected into a sound published manuscript.**
Nothing in these files asserts that any real paper contains an error. Manuscripts appear
only as opaque labels `M01`–`M21`, relations as `R01`–`R60`. The label-to-arXiv mapping is
not published, deliberately: a table naming third-party papers beside injected-defect
labels is the one artefact this release must never produce.

Verify before use:

    sha256sum -c docs/data/SHA256SUMS.txt      # from the repository root
    python -m reproducibility.verify_all       # recomputes and reconciles everything

---

## `fair_scoring_cells.json` — the per-cell outcome table

1,440 rows: 6 systems × 4 rungs × 60 relations. This is the file the headline results come
from, and the one the playground recomputes in your browser.

Rows are stored positionally under `fields` to keep the file small.

| field | meaning |
|---|---|
| `system` | evaluated system identifier; `gpt-5.2` is the proprietary replication |
| `rung` | `blind`, `category`, `relation`, `binary` |
| `cluster` | opaque manuscript label `M01`–`M21`; the bootstrap unit |
| `relation` | opaque relation label `R01`–`R60` |
| `family` | defect family (6) |
| `domain` | scientific domain (5) |
| `e0_scoreable` | 1 if the perturbed-state response could be scored |
| `e1_scoreable` | 1 if the as-published response could be scored |
| `e0_hit` | 1 if the tested relation was detected in E0; `null` when not scoreable |
| `e1_false_alarm` | 1 if the tested relation was flagged in E1, where it is sound |
| `e0_prov_gated` | 1 if the hit also satisfied the provenance gate |

**Denominators are per rung, not global.** A rung's complete-case set is the cells
scoreable in *both* states at *that* rung: 299, 297, 299, 299. Using one denominator for
every rung misstates three of the four rates — see discrepancies D1 and D2 below.

**The five open-weight systems are the published analysis.** The table also carries the
proprietary replication, so pooling all six is a different population and gives different
numbers. The playground defaults to the five.

## `fair_scoring_support.json` — audited aggregates for the ladder

Scorer-audit rates, the correction scenarios, and the proprietary accounting that the
per-cell table cannot carry because they are not per-cell quantities.

## `public_sufficient_statistics.json` — the other experiments

De-identified sufficient statistics: the broader benchmark, discovery ranking, bounded
agentic navigation, the eight-arm transfer experiment and the evidence profile. Paired
contrasts ship as **2×2 discordant cell counts** (`both`, `b`, `c`, `neither`), so a
paired interval can be recomputed. A difference of two independent arm rates is *not* the
same quantity and will not reproduce the published interval.

## `research_results.json` — aggregate outcome blocks

The three-state E0/E1/E2 task, the ladder decomposition, the four scorer-correction
scenarios, the frontier replications, the gold-label validation, the contamination
chronology, the denominator reconciliation and the miss anatomy. Numerators and
denominators are carried wherever the frozen record carries them.

Of note, because it is easy to miss: `contamination_chronology.ordering_verdict_by_system`
is **derived, not asserted**. It records, per system, whether the served checkpoint
predates every held-out manuscript. For two of six systems it does not, so chronology does
**not** rule memorisation out for them. That is a limit of the evidence, not a finding of
contamination.

## `scorer_audit_items.json` — human review, counts only

Two audits of the **scorer** — never of any person. Per item: the number of reviewers
choosing each of four categories.

That is enough to recompute majority verdicts, unanimity, per-stratum false-negative
rates, the population-reweighted rate and Fleiss' κ, all of which depend only on per-item
category counts.

**Withheld:** the reviewer axis and all free text. Six named colleagues are not
de-identifiable along that axis and no consent covering publication of individual
judgements exists. Consequently **mean pairwise agreement cannot be recomputed from this
file**; it is carried under `retained_audited_aggregates` and labelled as such rather than
quietly dropped.

## `manuscript_results_index.json` — the source-of-truth manifest

Every manuscript macro, its frozen value, the canonical record it came from, and its
reproduction route:

| route | meaning |
|---|---|
| `recomputable` | computable from the files in this directory |
| `audited_aggregate` | carried as a published aggregate; the underlying observations cannot safely be released |
| `restricted` | not published — see `DATA_SHARING_AND_PRIVACY_REVIEW.md` |
| `mixed` | parts of the value take different routes |

## `synthetic_demo_cells.json` — fabricated, not measured

Generated by a seeded RNG in `tools/make_synthetic_demo.py`. It declares itself
`"synthetic": true` and carries a warning against citation. It exists so the analysis can
be run and tested without touching the real outcomes. **It is not evidence.**

---

## Manuscript agreement

The **corrected** Nature Machine Intelligence manuscript of 2026-11-05 agrees with the
frozen record. `python -m reproducibility.verify_all` reports **zero current
discrepancies**.

The ten disagreements below were found against the **superseded draft** and were adopted
into the corrected manuscript. They are archived in
`reproducibility/manuscript_targets_archive.json`, not deleted, and are re-emitted as
`HISTORICAL_DISCREPANCIES.md` on every run so that the corrections remain auditable.

### Historical discrepancies against the superseded draft (archival)

| id | where | manuscript | canonical |
|---|---|---|---|
| D1 | §3B E0 denominators | 297 for all rungs | 299 / 297 / 299 / 299 |
| D2 | §3C E1 denominators | 300 for all rungs | 299 / 297 / 299 / 299 |
| D3 | §3B binary E0 hits | 147 | **148** |
| D4 | §3B blind sensitivity | 11.8% | 11.7% |
| D5 | §3B relation sensitivity | 20.2% | 20.1% |
| D6 | §3C relation balanced accuracy | 58.1% | 58.0% |
| D7 | Table 1, relation→binary d′ lower CI | +0.13 | +0.125 (exact 0.124956) |
| D8 | §3F GPT‑5.2 category / relation E0 | category 41.7%, relation 53.3% | **transposed** — category 53.3% (32/60), relation 41.7% (25/60) |
| D9 | §3F GPT‑5.2 pooled d′ | −0.07 | −0.0750335, which is **−0.08** at two decimals |
| D10 | §3B pooled descriptive raw relation→verdict | ≈ +29.3 pp | +29.4314 pp marginal (299 cells) **or** +29.8658 pp paired (298 cells) |

D7 is double rounding: 0.124956 → 0.125 at three decimals, and 0.125 was then rounded
again to 0.13. At two decimals the correct value is **+0.12**.

D3 is a genuine one-count difference in the headline rung and is not a rounding artefact.

The six paired contrasts of Table 1, both weightings, and all four weighting-sensitive
d′ results reproduce **exactly**, interval endpoints included.

## Paired estimates versus rung-marginal descriptives

These are different quantities on different denominators, and quoting one for the other
overstates or understates the effect:

| | relation → verdict, open-weight |
|---|---|
| **paired**, 298 eligible cells | 59 vs 148 hits → **+29.8658 pp** raw, **+12.7517 pp** balanced accuracy |
| **paired, system-balanced** | **+29.9548 pp** raw, +12.8051 pp balanced accuracy |
| **rung-marginal**, each rung on its own complete-case set | 60/299 vs 148/299 → **+29.4314 pp** |

The relation rung has 299 cells marginally and 298 in the paired set, because one cell is
unscoreable at the verdict rung and is therefore dropped from *both* sides of the pair.

## Reproducing the intervals exactly

The bootstrap resamples the 21 manuscripts, 10,000 draws, seed `20261016`, using Python's
stdlib Mersenne Twister with clusters visited in sorted order and a nearest-rank
percentile rule. `docs/assets/mt19937.js` reproduces that generator in JavaScript, so the
browser returns the same endpoints rather than endpoints from a different random source.
`tests/test_browser_bootstrap_parity.py` checks that against Python instead of asserting
it.
