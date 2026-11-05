# VerifierTrustBench

Research software for measuring when a language model's verdict on a scientific manuscript
counts as **verification** rather than a correct-looking guess.

This repository is a **code release**. It contains the protocol, the generation runners,
the scorers, the parsers and the statistical analysis — enough to read exactly what was
done and to run the whole methodology on manuscripts and models you obtain yourself. **It
does not contain the study's experimental results.** See
[What this repository does and does not contain](#what-this-repository-does-and-does-not-contain).

**Methodology demonstration:** <https://mkboch.github.io/VerifierTrustBench/> — runs the
analysis in your browser on a synthetic fixture, or on a file you supply.

---

## The measurement

Asking a model *"is anything wrong with this manuscript?"* and asking it *"is relation R
broken — yes or no?"* are different tests, and the gap between them is usually reported as
one quantity. It is at least two: **how much the system was told**, and **the shape of the
answer it had to give**. They move together unless you separate them on purpose.

So the protocol walks a ladder of four rungs, each changing exactly one thing:

| rung | information exposed | response interface |
|---|---|---|
| blind finding list | nothing is pointed at | ranked findings with cited lines |
| category-targeted finding list | the defect *family* is named | ranked findings with cited lines |
| relation-targeted finding list | the exact relation is named, in words | ranked findings with cited lines |
| relation-localized binary verdict | the same exact relation | a binary verdict with cited lines |

The last two carry **identical information**. Any difference between them is the response
format.

### Every rung is run twice

A system scored only on broken manuscripts is rewarded for suspicion: flag everything and
you look perceptive. So each rung runs in two evidence states on the same relation —
**E0**, with the tested relation deliberately broken, and **E1**, the manuscript exactly as
published, where that relation is sound. A flag in E1 is a false alarm, and it is counted.
A finding about some *other* part of the manuscript counts neither way, so the false-alarm
rate is specific to the relation under test.

```
sensitivity        = E0 hits / n
false-alarm rate   = E1 false alarms / n       (tested relation only)
specificity        = 1 − false-alarm rate
balanced accuracy  = (sensitivity + specificity) / 2
d′                 = z(hit rate) − z(false-alarm rate)
```

d′ uses the Hautus (1995) log-linear correction — `+0.5` to each count, `+1.0` to each
total — applied unconditionally, so the estimator is the same function everywhere.

Two rungs are compared on the **complete-case paired set**: cells where both rungs answered
scoreably in both states. Intervals come from a **manuscript-cluster bootstrap**, because
relations inside one manuscript are not independent; the whole estimand is recomputed in
each replicate. Two weightings are always reported — pooled, and equal-system — because
**they can disagree**, and a contrast reported without naming its weighting is not
interpretable.

### The Verification Evidence Profile

A single accuracy number hides what you want to know, so a verification episode is reported
as a profile over components that come apart from each other: information path, discovery,
ranking, localization, adjudication, evidence responsiveness, provenance, specificity, and
inter-agent transfer.

---

## Try the analysis in sixty seconds

```bash
git clone https://github.com/mkboch/VerifierTrustBench
cd VerifierTrustBench
pip install -r requirements-dev.txt

python tools/make_synthetic_demo.py          # regenerate the synthetic fixture
python src/analysis/fair_contrasts.py --data docs/data/synthetic_demo_cells.json
```

That prints the four-rung table and all six paired contrasts, each in both weightings, with
10,000-draw manuscript-cluster bootstrap intervals.

**The numbers it prints are not findings.** The input is fabricated by a seeded random
number generator (`tools/make_synthetic_demo.py`). It exists so the code can be run and
tested without publishing experimental outcomes. See
[`docs/data/SYNTHETIC_FIXTURE.md`](docs/data/SYNTHETIC_FIXTURE.md).

To analyse **your own** run, produce a file of the same schema with
`tools/build_fair_scoring_public.py` and pass it with `--data`, or load it into the
playground, which reads it in your browser and uploads it nowhere.

---

## What this repository does and does not contain

### Published here

- Corpus harvesting, data-only screening and seeded cohort selection.
- The relation miner and the **deterministic checkers**.
- E0 / E1 / E2 variant construction with line-preserving edits, and the dataset audit gate.
- Prompt construction, response schemas, exposure arms, seeds, and design-freeze machinery.
- The inference client (OpenAI-compatible HTTP) and every experiment runner.
- **The four-rung elicitation ladder**: protocol, prompt insertion, byte-equality self-test,
  runner, decomposition, bias-aware metrics, cluster-robust analysis, and the contamination,
  denominator and definitions audits.
- **The E0/E1 fair-scoring phase**: the canonical loader and scorer harness, the metrics,
  both E1 runners with their manifest and snapshot-drift guards, the miss anatomy, the
  scorer-sensitivity analysis, the scorer-audit analysis, and the reconciliations.
- **The frontier replication**: ladder runner, second-provider arm, preflight, probe, cost
  model, refusal and parser accounting, natural-error ledger.
- Scoring: verdict outcomes, strict blind discovery labels, provenance classification,
  Recall@k, evidence responsiveness, false-alarm rate.
- Paired-comparison utilities, exact McNemar, Newcombe intervals, GEE and mixed models,
  leave-one-paper / domain / family robustness.
- The bounded agentic navigation environment and runner.
- The length-matched rationale-control construction and analysis.
- The reusable Verification Evidence Profile harness.
- Figure-generation **code**, the template renderer, and the guard that fails a build if a
  statistic was typed by hand instead of substituted from a generated table.
- A public reference implementation of the headline analysis, tests, and a release audit.

### Deliberately not published here

- **The study's experimental results** — result tables, frozen numerical outcomes,
  per-relation records, aggregate statistics files, precomputed intervals, performance
  summaries, generated figures.
- **Raw model generations** and every inference or execution log.
- **Source manuscript text** — the corpus is third-party copyrighted material, and the
  relation ledgers embed excerpts.
- **The manuscript**, reviewer reports, audit records and internal research logs.
- **Human-participant data.** The scorer audit involved a small number of identifiable
  colleagues. No human judgment is published, in any form, aggregate or otherwise.
- Paper-specific checker modules whose regular expressions quote source-manuscript
  phrasing. The general-purpose miner and checkers that supersede them *are* published.

The one data file shipped is `docs/data/synthetic_demo_cells.json`, which declares itself
synthetic, carries a warning against being read as evidence, and is regenerable from its
generator. `scripts/audit_public_release.py` refuses to publish a data file that does not,
and the test suite fails if those markers are weakened or if a study result value appears
hard-coded anywhere in the tree.

### What you can actually reproduce

| | |
|---|---|
| read the exact protocol, scorers, parsers and analysis the study ran | **yes** |
| run the four-rung analysis end to end on data in the published schema | **yes** |
| check that the browser and the Python reference agree to machine precision | **yes** — the tests assert it |
| apply the whole methodology to manuscripts and models you obtain yourself | **yes** |
| recompute the manuscript's reported numbers from this repository | **no** |
| obtain the study's per-relation records, generations or human judgments | **no** — see the manuscript's availability statement |

**This repository supports methodological reproduction, not reproduction of the published
numbers.** Access to the controlled research dataset is described in the manuscript.

---

## Code structure

```
src/
  exp3heldout/        corpus harvesting, screening, cohort selection, the relation miner,
                      deterministic checkers, E0/E1/E2 construction, dataset audit,
                      design freeze, runner, evaluator, context gate, pipeline validation
  exp2b/              the frozen protocol: prompts, schemas, exposure arms, seeds, decision
                      rules, scoring, manuscript normalisation, inference client
  exp2br/             the repaired bounded-blind protocol and its runner
  exp2bbroad/         the broad multi-family replication
  nature_extension/
    reviewer_response_20261016/code/        the four-rung ladder
    final_topvenue_validation_20261018/code/ frontier replication
    fair_scoring_validation_20261020/code/  the E0/E1 fair-scoring phase
    verifier_profile/   the reusable Verification Evidence Profile harness
    phase0_methods/     re-analysis: GEE vs Bayes, BH FDR, screening funnel
    phase1_statistical_enrichment/  statistical-relation mining and analysis
    phase3_agentic/     content-neutral navigation environment, runner, analysis
    phase4_h3_control/  length-matched control construction, runner, analysis
  analysis/           fair_contrasts.py — reference implementation of the headline analysis
  paper_tools/        figure-generation code, template renderer, typed-number guard
  pilot/              the earliest pilot instrument, kept for lineage
tools/                make_synthetic_demo.py      the synthetic fixture generator
                      build_fair_scoring_public.py  turn YOUR frozen records into the schema
                      build_fair_scoring_support.py, build_public_statistics.py
                      update_manifest.py          regenerate docs/data/SHA256SUMS.txt
scripts/              audit_public_release.py — the release gate
tests/                checkers, scoring, the fixture, the analysis, the playground contract
docs/                 the GitHub Pages methodology demonstration
```

The research code resolves sibling modules by relative path, so the layout under `src/` is
preserved exactly as it was when the experiments ran. Most modules are byte-identical to
the files that produced the study's results; the few that hard-coded a machine-specific
path or an author contact address carry a minimal substitution for an environment variable.

---

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
```

Python 3.10+ (CI runs 3.10 and 3.12). Inference is served separately over an
OpenAI-compatible HTTP endpoint; nothing here loads a model in-process or downloads
weights.

### Configuration

`configs/models.json` lists model ids and endpoints. `prompts/questions.json` holds the
prompt scaffolding. Credentials are read from the environment; none is stored in this
repository, and the release audit fails if one appears.

Scripts that read a private research tree take its root from `VTB_ROOT`:

```bash
VTB_ROOT=/path/to/your/research/tree python tools/build_fair_scoring_public.py
```

---

## Tests

```bash
pytest                                  # the whole suite
python scripts/audit_public_release.py  # the publication gate
python tools/update_manifest.py --check # the served-file hash manifest is current
```

The suite covers the deterministic checkers, the frozen scorers, the synthetic fixture's
markers and regenerability, the analysis against regression anchors computed from that
fixture, parity between `docs/assets/fair.js` and `src/analysis/fair_contrasts.py`
(including bootstrap intervals, to machine precision), the playground's interaction
contract executed in a JS engine, and the release guards.

It also runs adversarial cases: inverted evidence states, a rung against itself, duplicated
relations, dropped data, and a halved corpus. **No test asserts a study result**; the
regression anchors come from the synthetic fixture.

---

## Citation and status

The accompanying manuscript is under review. Please cite the paper for the scientific
claims; cite this repository for the software.

## License

Apache-2.0. See [LICENSE](LICENSE).
