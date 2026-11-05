# How the published data files were derived

Three files are served: `fair_scoring_cells.json` and `fair_scoring_support.json` for the current four-rung fair-scoring study, and `public_sufficient_statistics.json` for the earlier benchmark analyses. The last section of this document covers the first two.

## `public_sufficient_statistics.json`

## What it is

The minimum aggregate needed for the browser to recompute the analyses offered in the playground.
Counts only: numerators, denominators, paired 2×2 cell counts, and condition labels.

## What produced it

`tools/build_public_statistics.py`, which is published in this repository. It was run as:

```
python tools/build_public_statistics.py \
    --private-root <the private research tree> \
    --out docs/data/public_sufficient_statistics.json
```

The script's **inputs are not published**. They are four frozen analysis artifacts in the private
research tree:

| input | what was taken from it |
|---|---|
| Experiment 3 `analysis.json` | the H1 paired 2×2 counts and marginal x/n, pooled and by model, defect family and domain |
| Phase 0 `profile.json` | Recall@k counts, verdict×provenance cell counts, responsiveness counts, false-alarm x/n |
| Phase 3 `phase3_analysis.json` | agentic vs direct paired counts, recall curves, tool-call distribution, false positives per case |
| Phase 4 `phase4_analysis.json` | the eight control-arm x/n and the six frozen paired contrasts |

Nothing was copied wholesale. The script selects named fields and discards everything else: the
helper `xn()` keeps only `x` and `n` from a rate block, and `paired()` keeps only the four cell
counts. The script refuses to write the file if any unexpected long string appears in the output.

## What is deliberately absent

- Per-case records, case identifiers, arXiv identifiers.
- Model generations, rationales, allegations, any free text produced by a model.
- Manuscript text of any kind.
- **All human-validation data.** Not a single aggregate from the human study is published. The study
  involved six identifiable colleagues, and omitting it entirely removes any reconstruction path.
- `FINAL_NUMBERS.json`, the paper's source-data tables, and the generated figures.

## Why ship paired cell counts

Because they are what makes genuine recomputation possible rather than redisplay. From `b` and `c`
alone the browser computes the exact two-sided McNemar p in integer arithmetic, and from the full
2×2 it computes a Newcombe method-10 interval. Both were verified against the frozen artifacts: all
24 published contrasts reproduce the stored exact p to double precision, and the recomputed
intervals agree with the stored intervals to within 0.02 pp (the stored values are rounded).

## A rounding note

The playground computes rates from `x/n`. The manuscript's pipeline formats a *stored* rate that was
itself already rounded, so a displayed percentage can differ by 0.1 pp — for example blind discovery
is 95/909, which is 10.451% (shown as 10.5% here) against 10.4% in the manuscript. The counts are
identical; only the rounding path differs.

## Honest limitation

GitHub Pages is a public static site. Everything in this file is readable by anyone, by design. The
protection is not obfuscation — it is that only aggregates were ever published.

## Integrity

```
sha256(public_sufficient_statistics.json) = 6b6f7ce79ff691e05db8ebf0af26fba1e7fcfef98964939702cee0f15ecd46c3
```

Regenerate the hash with `sha256sum docs/data/public_sufficient_statistics.json`, or verify the whole
release with `python scripts/audit_public_release.py`.


---

# `fair_scoring_cells.json`

## What it is

One row per **(system, rung, relation)** cell of the four-rung E0/E1 fair-scoring analysis:
1,440 rows for six systems × four rungs × sixty relations. Each row carries binary outcomes and
nothing else:

| field | meaning |
|---|---|
| `system`, `rung`, `cluster`, `relation` | identifiers; `cluster` is the manuscript, as an opaque label |
| `family`, `domain` | the defect family and the manuscript's subject area |
| `e0_scoreable`, `e1_scoreable` | whether the response was schema-valid and scoreable in that state |
| `e0_hit` | 1 if the system detected the injected defect in the perturbed state |
| `e1_false_alarm` | 1 if the system flagged the **same relation** when the manuscript was exactly as published |
| `e0_prov_gated` | verdict rung only: a correct E0 verdict whose cited evidence actually supports the tested relation |

This is the first release in which the paper's **current central result is reproducible from
published data**. Everything the playground shows for the ladder and the six paired contrasts —
sensitivity, specificity, balanced accuracy, log-linear d′, every paired difference and every
bootstrap interval — is computed from these rows in the visitor's browser.

## What produced it

`tools/build_fair_scoring_public.py`, published here. It runs **in the private research tree**, not
in a clone of this repository, and reads the frozen records through `fairlib.py`, the canonical
loader (also published, at `src/nature_extension/fair_scoring_validation_20261020/code/fairlib.py`):

```
VTB_ROOT=<the private research tree> python tools/build_fair_scoring_public.py
```

Nothing is rescored for the release. Scoring is done by the frozen scorers only —
`exp2b/scoring.py` `label_defective` for an E0 finding list, `label_clean` for an E1 finding list on
the tested relation, and the stored verdict for the binary rung. A finding about some other part of
the manuscript is not counted either way.

## What is deliberately absent

- **No model generation.** No finding text, no rationale, no evidence line, no verdict prose. Only
  the binary outcome a frozen scorer assigned.
- **No manuscript text**, and no prompt content.
- **No arXiv identifiers.** Manuscripts appear only as opaque cluster labels `M01`–`M21`, and
  relations as `R01`–`R60`. The cluster label is everything the estimand needs: the bootstrap
  resamples manuscripts, it does not read them.

  The reason is not secrecy. **An E0 cell is a defect this study injected into a sound published
  manuscript.** A public table naming third-party papers beside defect labels and detection
  outcomes invites exactly the misreading that those manuscripts are flawed. Publishing the
  label-to-identifier mapping is an author decision; it would be a one-file addition and would not
  change a single number.
- No human-participant record of any kind.

## Why per-cell rows rather than aggregates

Because the paper's headline is a **paired, clustered** estimate. A visitor given only per-rung
marginals could redisplay a difference but could not form the complete-case paired set, could not
resample manuscripts, and could not recompute an interval. Binary outcome labels are derived
measurements rather than model output, so publishing them redistributes nothing belonging to a
model provider or to an arXiv author — and they make the central claim genuinely checkable instead
of merely asserted.

## Reproducing the headline

```
python src/analysis/fair_contrasts.py
```

against the published file alone. `tests/test_fair_scoring.py` asserts that the point estimates it
produces match the independent audit of 2026-11-04 to three decimals, and that
`docs/assets/fair.js` returns the same values in a JS engine.

### One documented difference from the frozen analysis

The bootstrap PRNG. The frozen research analysis used Python's Mersenne Twister. The public
reference and the browser both use **mulberry32**, because it is bit-reproducible in both
languages, which is what lets the test suite prove the browser is not lying. Same procedure, same
seed (20261016), same 10,000 draws, same resampling unit — a different random stream, so the
Monte-Carlo interval differs slightly. **Point estimates are unaffected and identical.** The
measured agreement is recorded in the release report.

---

# `fair_scoring_support.json`

## What it is

The two blocks that are not per-cell quantities:

- **`scorer_audit`** — the human audit of relation-targeted misses: six colleagues rated thirty
  sampled items under a stratified, non-proportional design. Published: the stratum rates, the
  reweighted headline rate and its interval, the item- and judgment-level counts, Fleiss κ and mean
  pairwise raw agreement, and the four correction scenarios.
- **`proprietary_replication`** — the Anthropic arm's refusal and parser accounting. Counts only.

## These are static audited aggregates, and the site says so

Their intervals were computed by the frozen analysis **from per-reviewer judgments that are not
published**, because six identifiable colleagues produced them. A visitor cannot regenerate them
from anything served here. The playground labels this analysis as not recomputed, rather than
presenting a precomputed interval as if the browser had derived it.

No per-reviewer and no per-pair figure is published — only the aggregate agreement statistics.

## What produced it

`tools/build_fair_scoring_support.py`, run the same way, reading `SCORER_SENSITIVITY.json`,
`RT_AUDIT_RESULTS.json` and `ANTHROPIC_ACCOUNTING.json` from the frozen analysis tree.

## Integrity

Hashes for every served file are in `docs/data/SHA256SUMS.txt`, regenerated by
`python tools/update_manifest.py` and enforced by `tests/test_release_manifest.py`. The playground
prints the relevant manifest line inside each derivation.
