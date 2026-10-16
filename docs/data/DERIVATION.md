# How `public_sufficient_statistics.json` was derived

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
