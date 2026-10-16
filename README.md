# VerifierTrustBench

> **When should an AI verifier's conclusion count as scientific verification, rather than merely a
> correct-looking verdict?**

A language model asked to check a manuscript will produce a verdict. Whether that verdict is worth
anything depends on how it was reached: whether the model found the problem or was handed it,
whether it cited the lines that actually carry the claim, whether its judgment moves when the
underlying evidence changes. Current practice collapses all of this into one accuracy number, and
that number is dominated by whichever sub-capability a given benchmark happens to exercise.

This repository holds the **reproducibility code** for a study that pulls those components apart,
plus an **interactive playground** that recomputes the headline analyses in your browser from
published aggregate counts.

---

## The Verification Evidence Profile

Rather than score a verification episode, we report it as a profile. The components dissociate
empirically — a system can be strong on one and weak on the next — which is the reason the profile
exists.

| Component | The question it answers |
|---|---|
| **Information path** | How did the relation reach the verifier: blind discovery, category-targeted, relation-localized, or supplied by an upstream agent? |
| **Discovery** | With nothing pointed at, does the system find the defect at all? |
| **Ranking** | If it was surfaced, where in the finding list did it appear? Is a miss really a mis-ranking? |
| **Localization** | Told what to check, can the system reach the lines that carry the relation? |
| **Adjudication** | Given the right lines, does it rule correctly? |
| **Evidence responsiveness** | Does the verdict change when the evidence changes — defective (E0), unmodified (E1), independently re-perturbed (E2)? |
| **Provenance** | Does the cited line actually support the tested relation, or merely exist? |
| **Specificity** | How often is a perfectly valid relation flagged as broken? |
| **Inter-agent information transfer** | What does one verifier's output do to the next verifier's judgment — the evidence, or the label? |

The substrate is deliberately conservative. Rather than author synthetic errors, the pipeline mines
**native** quantitative relations already present in real manuscripts and certifies each one with a
**deterministic checker**: a relation is admitted only if the checker returns *consistent* on the
unmodified text and *inconsistent* on a controlled counterfactual. Primary gold is a program output,
never a model's or an annotator's opinion.

---

## What this repository contains, and what it does not

This is a **code release**. It is intentionally not a data release.

**Published here**

- Corpus harvesting, data-only screening, and seeded cohort selection.
- The native relation miner and the **deterministic checkers**.
- E0 / E1 / E2 variant construction with line-preserving edits, and the dataset audit gate.
- Prompt construction, response schemas, exposure arms, seeds, and the design-freeze machinery.
- The inference client (OpenAI-compatible HTTP) and the experiment runners.
- Scoring: verdict outcomes, strict blind discovery labels, provenance classification, Recall@k,
  evidence responsiveness, false-alarm rate.
- Paired comparison utilities, exact McNemar, Newcombe intervals, GEE and mixed-model analyses, and
  leave-one-paper / domain / family robustness code.
- The bounded agentic navigation environment and runner.
- The length-matched rationale-control (H3) construction and analysis.
- The statistical-enrichment miner and its analysis.
- The reusable Verification Evidence Profile harness.
- Figure-generation **code**, and the template renderer plus the guard that fails a build if any
  statistic was typed by hand instead of substituted from a generated table.
- Tests, and a public-release audit script.

**Deliberately excluded from this initial release**

- **Raw model generations** and every inference or execution log.
- **Source manuscript text** — the corpus is third-party copyrighted material, and the relation
  ledgers embed excerpts from it.
- **Full result artifacts**: run directories, frozen analysis JSON, case ledgers, design manifests.
- **Generated paper figures**, the manuscript in any form, and the paper's source-data tables.
- **Identifiable human-validation data.** The study's human validation involved six identifiable
  colleagues; no human data is published here, not even in aggregate.
- Five paper-specific checker modules whose regular expressions quote source-manuscript phrasing.
  The general-purpose miner and checkers that supersede them *are* published.

The release is audited mechanically. `scripts/audit_public_release.py` fails non-zero on secrets,
personal paths, participant data, figures, manuscripts, raw records, model weights or oversized
files, and the same guarantees are re-checked by `tests/test_no_forbidden_content.py` in CI.

---

## Three distinct things

Keeping these apart is the point of the release design.

1. **Published code** — this repository. Enough to understand and re-run the methodology on
   manuscripts and models you obtain yourself.
2. **Frozen private scientific artifacts** — the corpus, the relation ledgers, every model
   generation, the frozen analyses and the manuscript. Held privately. Nothing in this repository
   modifies them, and no number here was transcribed by hand from them.
3. **Interactive aggregate playground** — a static site shipping only de-identified aggregate
   counts, sufficient for a visitor to recompute the headline analyses and nothing more.

---

## Code structure

```
src/
  exp3heldout/        corpus harvesting, screening, cohort selection, the relation miner,
                      the deterministic checkers, E0/E1/E2 construction, dataset audit,
                      design freeze, runner, evaluator, context gate, pipeline validation
  exp2b/              the frozen protocol: prompts, schemas, exposure arms, seeds, decision
                      rules, scoring (verdict outcomes, provenance, strict blind labels),
                      manuscript normalisation and line indexing, inference client
    cases/common.py   generic numeric-extraction helpers for hand-written checkers
    papers/           generic corpus preparation and screening tooling
  exp2br/             the repaired bounded-blind protocol (BLIND_SCHEMA_BR) and its runner
  exp2bbroad/         the broad multi-family replication
  nature_extension/
    verifier_profile/ the reusable Verification Evidence Profile harness (+ its self-test)
    phase0_methods/   re-analysis from frozen records: GEE vs Bayes, BH FDR, screening funnel
    phase1_statistical_enrichment/  prospective statistical-relation mining and analysis
    phase3_agentic/   content-neutral manuscript-navigation environment, runner, analysis
    phase4_h3_control/ length-matched irrelevant/filler construction, runner, analysis
  paper_tools/        figure-generation code, the strict template renderer, and the
                      hand-typed-number guard
  pilot/              the earliest pilot instrument, kept for lineage
tools/                build_public_statistics.py — derives the playground aggregate
scripts/              audit_public_release.py — the release gate
tests/                checkers, scoring, aggregate consistency, playground contract, guards
docs/                 the GitHub Pages playground (index.html, assets/, data/)
```

The research code resolves sibling modules by relative path, so the directory layout under `src/`
is preserved exactly as it was when the experiments ran.

---

## Setup

```bash
git clone https://github.com/mkboch/VerifierTrustBench.git
cd VerifierTrustBench
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

Python 3.10+. Nothing here loads model weights in-process or downloads anything at import time.

### Configuration

Server-specific values were removed from the published copy and replaced with environment
variables. Set what you need:

| Variable | Meaning | Default |
|---|---|---|
| `VTB_ROOT` | repository root used by the shell drivers | inferred from the script location |
| `VTB_PYTHON` | interpreter the shell drivers invoke | `python3` |
| `VTB_SOURCE_DIR` | where harvested LaTeX sources are written and read | `sources/<phase>` |
| `VTB_VLLM_ENV` | prefix of your vLLM environment (serving scripts only) | required if serving |
| `VTB_VLLM_CACHE` | vLLM cache root | `$HOME/.cache/vllm` |
| `HF_HOME` | Hugging Face cache | `$HOME/.cache/huggingface` |

Endpoints and ports live in `configs/models.json`. The serving scripts in `src/exp3heldout/serve3.sh`
and `src/exp2b/orchestrate.sh` assume a local OpenAI-compatible server per model; adapt them to your
own hardware rather than expecting them to run unchanged.

## Running the tests

```bash
pytest                                   # the whole suite
pytest tests/test_checkers.py            # the deterministic checkers
pytest tests/test_playground.py          # executes docs/assets/app.js in a JS engine
python scripts/audit_public_release.py   # the release gate
```

The playground tests need the optional `quickjs` package; they are skipped without it. No test
requires a GPU, a model, or any private artifact.

## Running the pipeline on your own material

The code is written to be re-pointed, not to ship a dataset.

1. **Obtain manuscripts you have the right to use** and place their LaTeX sources under
   `$VTB_SOURCE_DIR/<id>/`. `src/exp3heldout/harvest.py` shows how the study retrieved candidates;
   screening in `prepare_screen.py` is data-only and uses no model.
2. **Mine and certify relations** with `src/exp3heldout/mine_cases.py`. A candidate is admitted only
   if `checkers.check()` returns `True` on the unmodified text and `False` on the perturbation.
3. **Build the variants and audit them** — `build_dataset.py`, then `audit_dataset.py`, which applies
   the ten pre-freeze checks.
4. **Freeze** with `freeze_heldout.py`. The runner refuses to start if a hashed input changed.
5. **Serve your models** (any OpenAI-compatible endpoint) and run `run_heldout.py`.
6. **Score and analyse** with `evaluate_heldout.py`, then build the profile with
   `src/nature_extension/verifier_profile/run_profile.py`.

Steps 1–4 involve no model at any point. That separation is deliberate: gold is produced by programs
before any verifier sees anything.

---

## Interactive Playground

**https://mkboch.github.io/VerifierTrustBench/**

The playground ships **no result on load**. There is no chart in the page and no headline percentage
in the markup. You pick an analysis, choose settings, and press **Reproduce result**; only then does
JavaScript read the aggregate counts, compute the metric, and build the result card and chart.
**Reset** removes them again.

Five analyses are available: discovery versus relation-localized verification (sliceable by system,
defect family and domain), Recall@k over the blind finding list, bounded agentic navigation,
information transfer between verifiers across eight length-matched arms, and the full Verification
Evidence Profile for one system.

Every card shows its numerator, denominator and formula, and **How was this calculated?** opens the
full derivation including the exact-McNemar computation. The exact p-values are recomputed in the
browser in integer arithmetic from the discordant counts; all 24 published contrasts reproduce the
frozen values to double precision.

The data file is `docs/data/public_sufficient_statistics.json`, derived by
`tools/build_public_statistics.py` and documented in [`docs/data/DERIVATION.md`](docs/data/DERIVATION.md)
with a SHA256 manifest. It contains counts and labels — no per-case records, no model output, no
manuscript text, no human-participant data.

No cookies, no analytics, no external requests, no CDN, no API keys, no model inference.

---

## Status and citation

The study is complete and the manuscript is under internal review. **It has not been accepted or
published anywhere.** There is no DOI and no citation to give yet; please do not invent one. If you
want to reference this work before a paper exists, link to this repository.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

Note separately that the manuscripts the pipeline operates on are third-party copyrighted works.
None are redistributed here, and any reuse of the methodology needs sources you have the right to
process.
