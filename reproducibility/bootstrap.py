"""The manuscript-cluster bootstrap, reproduced exactly as the frozen analysis ran it.

WHY THIS IS NOT "a bootstrap" BUT "THE bootstrap"

An interval is only reproducible if the resampling is reproducible, and that means the
random number generator, its seeding, the order the clusters are visited in, the number of
draws and the percentile rule must all match. They do:

  generator        Python's stdlib Mersenne Twister, random.Random(seed)
  seed             20261016 for the ladder, as frozen
  draws            10000
  unit             the manuscript, never the cell -- 21 clusters resampled with replacement
  order            clusters visited as sorted(units), so the draw sequence is deterministic
  index            rng.randrange(len(keys)) per draw
  percentile       vals[int(0.025 * (len(vals) - 1))] and vals[int(0.975 * (len(vals) - 1))]
                   on the sorted replicate values -- a nearest-rank rule, not interpolation

The whole estimand is recomputed inside every replicate. Rates are never resampled: a
resampled rate is a different and wrong quantity.

A replicate whose statistic is undefined (an empty eligible set, say) is dropped. If more
than half the draws are dropped, no interval is returned at all rather than a misleading
one computed from a biased remnant.

Python's Mersenne Twister is specified and stable across versions, so this file reproduces
the frozen interval endpoints exactly -- not approximately.
"""
from __future__ import annotations
import random

DRAWS = 10000
LADDER_SEED = 20261016


def cluster_bootstrap(units: dict, stat, draws: int = DRAWS, seed: int = LADDER_SEED):
    """units maps cluster -> list of items; stat maps a flat item list to a float or None.

    Returns (point, lo, hi, n_valid_replicates).
    """
    keys = sorted(units)
    rng = random.Random(seed)
    point = stat([x for k in keys for x in units[k]])
    vals = []
    for _ in range(draws):
        samp = []
        for _ in range(len(keys)):
            samp += units[keys[rng.randrange(len(keys))]]
        v = stat(samp)
        if v is not None:
            vals.append(v)
    if len(vals) < draws * 0.5:
        return point, None, None, len(vals)
    vals.sort()
    lo = vals[int(0.025 * (len(vals) - 1))]
    hi = vals[int(0.975 * (len(vals) - 1))]
    return point, lo, hi, len(vals)
