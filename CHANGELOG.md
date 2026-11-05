# Changelog

## 2026-11-05 — GPT-5.2 blind E0 export corrected

**Commit `fd4b291f` exported GPT-5.2 blind E0 outcomes incorrectly, and this release
corrects them.** The published blind E0 total was **2/60**; it should have been **18/60**.

### What was wrong

The frontier loader keyed every blind finding-list response by *manuscript*:

```python
blind_by_paper[r["paper"]] = r          # one response kept per manuscript
```

That is right for E1 and wrong for E0, because the two runners differ:

- the **E0** runner issued one blind request **per relation**, each against that relation's
  own perturbed manuscript — 60 requests, 60 distinct case ids;
- the **E1** runner issued one blind request **per manuscript** — 21 requests, because the
  manuscript as published is the same document whichever relation is under test.

Keying by manuscript in E0 therefore discarded three of every four responses, kept the
last, and scored it against relations whose defects it had never been shown. Sixteen cells
that were genuine detections were exported as misses.

The open-weight loader in the same module already drew this distinction — its own comment
reads *"E0 per relation, E1 per paper"*. Only the frontier path lost it.

### How it was found and checked

The released data was internally inconsistent: `research_results.json` carried the
canonical **18/60**, while `fair_scoring_cells.json` summed to **2/60**. Nothing caught it,
because the reproducibility suite excluded GPT-5.2 from every cell-level test.

Before publishing the correction, all 60 blind E0 cases were reconciled one by one against
the frozen trial records and `FRONTIER_ITEMLEVEL.csv`, comparing the selected trial key,
status, parsed response and hit judgment. **All 60 reconcile.** Sixteen cells change, every
one from 0 to 1; none changes the other way.

The two pipelines use different JSON acceptance rules — the frontier analysis strips code
fences and falls back to a brace scan, the fair-scoring parser requires schema validation
with no fallback. On these 60 responses the rules agree exactly, because every response was
schema-valid and the fallback never engaged. They remain different protocols and are not
treated as interchangeable.

### What changed, and what did not

| | |
|---|---|
| Cells changed | **16**, all `gpt-5.2` / `blind`, field `e0_hit`, all 0 → 1 |
| Open-weight rows | **unchanged** |
| GPT-5.2 E1 outcomes | **unchanged** (false alarms 0, 1, 0, 2) |
| GPT-5.2 category, relation, binary E0 | **unchanged** (32, 25, 39) |
| Frozen research records | **not modified** |

`docs/data/fair_scoring_cells.json`
`0a6081f72c555a419d6077ef41d2552b97ab0fb35b6d8210f9bd03c426b883e2` →
`aaae01eb2c281af177b8ba2c4fc2f65c51872a3795d94d8f70fa1fc698379ada`

### Does this change any main finding?

**No.** The study's headline results are the five open-weight systems, and not one
open-weight value moves. The four-rung ladder, all six paired contrasts, both weightings,
every confidence interval and the scorer-audit analysis are identical.

What changes is the **proprietary replication**, reported as a secondary result. With the
correction, GPT-5.2's ladder is 30.0% / 53.3% / 41.7% / 65.0%, and relation → verdict is
+23.33 pp raw, +10.0 pp balanced accuracy (95% CI [+2.5, +17.0]) and d′ −0.075 (95% CI
[−0.66, +0.80], which includes zero). The qualitative reading is unchanged: the response
format moves the raw rate while the discrimination index does not.

### Also corrected in the release

- `tools/frontier_blind_fix.py` carries the corrected loader. The staged copy of the frozen
  `fairlib.py` is left **byte-identical to the module that actually ran**, because it is
  the historical record of the analysis; the correction is applied as a subclass.
- `reproducibility/verify_all.py` gained 76 GPT-5.2 and estimand assertions, including a
  cross-check that the per-cell table agrees with the canonical frontier aggregate.
- `tests/test_frontier_blind_export.py` asserts that blind E0 outcomes vary within a
  manuscript — the structural signature that manuscript-level deduplication destroys — so
  the bug cannot return and be hidden by editing an expected total.
