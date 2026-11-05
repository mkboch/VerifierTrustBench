/* Four-rung E0/E1 fair-scoring analysis, recomputed in the visitor's browser from
   docs/data/fair_scoring_cells.json.

   This file is the JavaScript twin of src/analysis/fair_contrasts.py. The two share a
   PRNG (mulberry32) chosen because it is bit-reproducible in both languages, so the
   browser and the Python reference return identical intervals from identical inputs.
   tests/test_fair_scoring.py executes this file and compares the two.

   Nothing here is hard-coded from the manuscript. Every sensitivity, specificity,
   balanced accuracy, d-prime, difference and confidence interval the page shows for this
   analysis is derived from the per-cell rows at run time. */
"use strict";

(function (root) {
  const DRAWS = 10000, SEED = 20261016;
  const ORDER = ["blind", "category", "relation", "binary"];
  const CONTRASTS = [
    ["blind", "category"], ["blind", "relation"], ["category", "relation"],
    ["relation", "binary"], ["category", "binary"], ["blind", "binary"],
  ];

  /* ------------------------------------------------------------------ prng */
  /* mulberry32. Identical stream to Mulberry32 in src/analysis/fair_contrasts.py. */
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* ------------------------------------------------------------------ metrics */
  /* Inverse standard normal CDF: Acklam, refined by one Halley step against erfc. */
  function erfc(x) {
    /* Numerical Recipes incomplete-gamma-free rational approximation, |eps| < 1.2e-7,
       then one Newton step is unnecessary: the Halley step below uses it only to correct
       Acklam, whose own error dominates. */
    const z = Math.abs(x), t = 2 / (2 + z);
    const ty = 4 * t - 2;
    const cof = [-1.3026537197817094, 6.4196979235649026e-1, 1.9476473204185836e-2,
      -9.561514786808631e-3, -9.46595344482036e-4, 3.66839497852761e-4,
      4.2523324806907e-5, -2.0278578112534e-5, -1.624290004647e-6,
      1.303655835580e-6, 1.5626441722e-8, -8.5238095915e-8,
      6.529054439e-9, 5.059343495e-9, -9.91364156e-10,
      -2.27365122e-10, 9.6467911e-11, 2.394038e-12,
      -6.886027e-12, 8.94487e-13, 3.13092e-13,
      -1.12708e-13, 3.81e-16, 7.106e-15];
    let d = 0, dd = 0;
    for (let j = cof.length - 1; j > 0; j--) { const tmp = d; d = ty * d - dd + cof[j]; dd = tmp; }
    const ans = t * Math.exp(-z * z + 0.5 * (cof[0] + ty * d) - dd);
    return x >= 0 ? ans : 2 - ans;
  }

  function z(p) {
    const a = [-3.969683028665376e+1, 2.209460984245205e+2, -2.759285104469687e+2,
      1.383577518672690e+2, -3.066479806614716e+1, 2.506628277459239e+0];
    const b = [-5.447609879822406e+1, 1.615858368580409e+2, -1.556989798598866e+2,
      6.680131188771972e+1, -1.328068155288572e+1];
    const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838e+0,
      -2.549732539343734e+0, 4.374664141464968e+0, 2.938163982698783e+0];
    const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996e+0,
      3.754408661907416e+0];
    const pl = 0.02425, ph = 1 - 0.02425;
    let x, q, r;
    if (p < pl) {
      q = Math.sqrt(-2 * Math.log(p));
      x = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
          ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1);
    } else if (p <= ph) {
      q = p - 0.5; r = q * q;
      x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q /
          (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
    } else {
      q = Math.sqrt(-2 * Math.log(1 - p));
      x = -((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1));
    }
    const e = 0.5 * erfc(-x / Math.SQRT2) - p;
    const u = e * Math.sqrt(2 * Math.PI) * Math.exp((x * x) / 2);
    return x - u / (1 + (x * u) / 2);
  }

  /** d' with the Hautus (1995) log-linear correction, applied unconditionally. */
  function loglinearDprime(hits, nSig, fas, nNoise) {
    return z((hits + 0.5) / (nSig + 1)) - z((fas + 0.5) / (nNoise + 1));
  }

  function agg(cells) {
    const n = cells.length;
    if (!n) return null;
    let h = 0, fa = 0;
    for (const c of cells) { h += c.hit; fa += c.fa; }
    const sens = h / n, far = fa / n;
    return {
      n, hits: h, false_alarms: fa,
      sensitivity_pct: 100 * sens, false_alarm_rate_pct: 100 * far,
      specificity_pct: 100 * (1 - far),
      balanced_accuracy_pct: (100 * (sens + 1 - far)) / 2,
      dprime: loglinearDprime(h, n, fa, n),
    };
  }

  /* ------------------------------------------------------------------ data */
  function parse(doc) {
    const ix = {};
    doc.fields.forEach((f, i) => { ix[f] = i; });
    const cells = new Map();
    for (const row of doc.cells) {
      const key = row[ix.system] + "|" + row[ix.rung] + "|" + row[ix.relation];
      cells.set(key, {
        system: row[ix.system], rung: row[ix.rung], cluster: row[ix.cluster],
        relation: row[ix.relation], family: row[ix.family], domain: row[ix.domain],
        scoreable: !!row[ix.e0_scoreable] && !!row[ix.e1_scoreable],
        hit: row[ix.e0_hit] || 0, fa: row[ix.e1_false_alarm] || 0,
        prov: row[ix.e0_prov_gated],
      });
    }
    const relations = [...new Set(doc.cells.map((r) => r[ix.relation]))].sort();
    return { doc, cells, relations };
  }

  /** Complete-case paired set: both rungs scoreable in both evidence states. */
  function eligible(D, a, b, systems) {
    const out = [];
    for (const s of systems) {
      for (const r of D.relations) {
        const ca = D.cells.get(s + "|" + a + "|" + r), cb = D.cells.get(s + "|" + b + "|" + r);
        if (ca && cb && ca.scoreable && cb.scoreable) {
          out.push({ system: s, cluster: ca.cluster, a: ca, b: cb });
        }
      }
    }
    return out;
  }

  const side = (pairs, k) => pairs.map((p) => p[k]);

  function pooledDiff(pairs, metric) {
    const A = agg(side(pairs, "a")), B = agg(side(pairs, "b"));
    return A && B ? B[metric] - A[metric] : null;
  }

  function balancedDiff(pairs, metric) {
    const by = new Map();
    for (const p of pairs) {
      if (!by.has(p.system)) by.set(p.system, []);
      by.get(p.system).push(p);
    }
    const vals = [];
    for (const s of [...by.keys()].sort()) {
      const ps = by.get(s);
      const A = agg(side(ps, "a")), B = agg(side(ps, "b"));
      if (!A || !B) return null;
      vals.push(B[metric] - A[metric]);
    }
    return vals.length ? vals.reduce((x, y) => x + y, 0) / vals.length : null;
  }

  /** Manuscript-cluster bootstrap. The whole estimand is recomputed per replicate. */
  function clusterBootstrap(pairs, stat, draws, seed) {
    draws = draws || DRAWS;
    seed = seed === undefined ? SEED : seed;
    const by = new Map();
    for (const p of pairs) {
      if (!by.has(p.cluster)) by.set(p.cluster, []);
      by.get(p.cluster).push(p);
    }
    const keys = [...by.keys()].sort();
    const rng = mulberry32(seed);
    const point = stat(pairs);
    const vals = [];
    for (let d = 0; d < draws; d++) {
      const samp = [];
      for (let i = 0; i < keys.length; i++) {
        const bucket = by.get(keys[Math.floor(rng() * keys.length)]);
        for (const x of bucket) samp.push(x);
      }
      const v = stat(samp);
      if (v !== null && !Number.isNaN(v)) vals.push(v);
    }
    if (vals.length < draws * 0.5) {
      return { point, lo: null, hi: null, used: vals.length, clusters: keys.length };
    }
    vals.sort((x, y) => x - y);
    return {
      point,
      lo: vals[Math.floor(0.025 * (vals.length - 1))],
      hi: vals[Math.floor(0.975 * (vals.length - 1))],
      used: vals.length, clusters: keys.length,
    };
  }

  /** Per-rung marginals on each rung's own eligible cells (descriptive, not paired). */
  function ladderTable(D, systems) {
    const out = {};
    const set = new Set(systems);
    for (const rung of ORDER) {
      const xs = [];
      for (const c of D.cells.values()) {
        if (c.rung === rung && set.has(c.system) && c.scoreable) xs.push(c);
      }
      out[rung] = agg(xs);
    }
    return out;
  }

  function contrast(D, a, b, systems, weighting, metric, draws, seed) {
    const pairs = eligible(D, a, b, systems);
    const fn = weighting === "pooled" ? pooledDiff : balancedDiff;
    const boot = clusterBootstrap(pairs, (ps) => fn(ps, metric), draws, seed);
    const excludesZero = boot.lo !== null && (boot.lo > 0 || boot.hi < 0);
    return {
      a, b, metric, weighting,
      n_cells: pairs.length,
      n_systems: new Set(pairs.map((p) => p.system)).size,
      A: agg(side(pairs, "a")), B: agg(side(pairs, "b")),
      point: boot.point, lo: boot.lo, hi: boot.hi,
      n_clusters: boot.clusters, draws_used: boot.used,
      draws: draws || DRAWS, seed: seed === undefined ? SEED : seed,
      excludesZero,
      verdict: excludesZero
        ? "difference detected"
        : "interval includes zero; no improvement established",
    };
  }

  root.VTBFair = {
    DRAWS, SEED, ORDER, CONTRASTS,
    mulberry32, z, loglinearDprime, agg, parse, eligible,
    pooledDiff, balancedDiff, clusterBootstrap, ladderTable, contrast,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
