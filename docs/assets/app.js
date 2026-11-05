/* VerifierTrustBench methodology demonstration.

   Nothing is computed until the visitor asks for it, and nothing it computes is an
   experimental result. The input is either the synthetic fixture shipped with this
   repository -- fabricated by tools/make_synthetic_demo.py -- or a file the visitor loads
   from their own computer, which is read locally and never transmitted.

   The analysis itself is VTBFair, in fair.js, which is the JavaScript twin of
   src/analysis/fair_contrasts.py. This file is only the interface around it. */
"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, kids = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(kids)) {
    n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return n;
};
const svgEl = (tag, attrs = {}) => {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};

let DATA = null;        // parsed cell table currently loaded
let ORIGIN = null;      // {kind: "synthetic"|"upload", label, synthetic: bool}

/* ---------------------------------------------------------------- formatting */

const fmtPct = (v) => (Number.isFinite(v) ? v.toFixed(1) + "%" : "n/a");
const fmtD = (v) => (Number.isFinite(v) ? v.toFixed(3) : "n/a");
const fmt3 = (v) =>
  Number.isFinite(v) ? (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(3) : "n/a";

const RUNG_SHORT = {
  blind: "Blind list", category: "Category-targeted list",
  relation: "Relation-targeted list", binary: "Relation-localized verdict",
};
const CONTRAST_LABELS = {
  "blind->category": "Blind → category-targeted finding list",
  "blind->relation": "Blind → relation-targeted finding list",
  "category->relation": "Category-targeted → relation-targeted finding list",
  "relation->binary": "Relation-targeted finding list → relation-localized verdict",
  "category->binary": "Category-targeted finding list → relation-localized verdict",
  "blind->binary": "Blind → relation-localized verdict (first rung to last)",
};
const METRIC_LABEL = {
  balanced_accuracy_pct: "balanced accuracy (pp)",
  dprime: "d′ (log-linear corrected)",
};
const HINTS = {
  ladder: "Each rung summarised on its own eligible cells: what it detected on a broken relation, and what it flagged on the same relation when it was sound.",
  contrasts: "Two rungs compared on identical cells, with a 10,000-draw manuscript-cluster bootstrap interval computed here in your browser.",
  table1: "All six contrasts at once, under both weightings, so a contrast that changes sign or loses significance when the weighting changes is visible rather than hidden.",
  experiments: "Findings that are not rung contrasts: the broader benchmark, the three evidence states, bounded agentic navigation, and what transfers between verifiers.",
  frontier: "The two proprietary replications, including the refusals and unparseable outputs that are excluded from the strict denominator rather than scored as errors.",
  scorer: "What six colleagues said when asked whether the scorer was right, and the four correction scenarios that follow from it. Per-item counts only.",
};

/* ---------------------------------------------------------------- building blocks */

function table(headers, rows) {
  const t = el("table");
  const thead = el("thead");
  thead.appendChild(el("tr", {}, headers.map((h) => el("th", { text: h }))));
  t.appendChild(thead);
  const tb = el("tbody");
  for (const r of rows) {
    tb.appendChild(el("tr", {}, r.map((c, i) =>
      el("td", {
        // right-align only cells that hold a number; several columns here are prose
        class: i === 0 || !/^[+\-−]?[\d.,%\s/–-]*\d[\d.,%\s/–-]*$/.test(String(c))
          ? "" : "num",
        text: String(c),
      }))));
  }
  t.appendChild(tb);
  return el("div", { class: "tablewrap", role: "region", tabindex: "0",
                     "aria-label": headers.join(", ") }, [t]);
}

function barChart(bars, opts = {}) {
  const W = 640, rowH = 46, padL = 190, padR = 70, padT = 14;
  const H = padT + bars.length * rowH + 14;
  const max = opts.max || Math.max(100, ...bars.map((b) => b.value));
  const svg = svgEl("svg", {
    viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": opts.alt || "Bar chart of the computed values",
  });
  const scale = (v) => ((W - padL - padR) * v) / max;
  for (const t of [0, 0.25, 0.5, 0.75, 1].map((f) => f * max)) {
    const x = padL + scale(t);
    svg.appendChild(svgEl("line", { x1: x, y1: padT, x2: x, y2: H - 20,
      stroke: "currentColor", "stroke-opacity": t === 0 ? 0.45 : 0.14 }));
    const lab = svgEl("text", { x, y: H - 6, "text-anchor": "middle", "font-size": 11,
      "fill-opacity": 0.6 });
    lab.textContent = opts.unit === "d" ? t.toFixed(1) : Math.round(t) + "%";
    svg.appendChild(lab);
  }
  bars.forEach((b, i) => {
    const y = padT + i * rowH + 8;
    const name = svgEl("text", { x: padL - 10, y: y + 16, "text-anchor": "end",
      "font-size": 12.5 });
    name.textContent = b.label;
    svg.appendChild(name);
    svg.appendChild(svgEl("rect", { x: padL, y, width: Math.max(1, scale(b.value)),
      height: 24, rx: 3, fill: b.color || "#2f6690" }));
    const val = svgEl("text", { x: padL + scale(b.value) + 8, y: y + 17,
      "font-size": 12.5, "font-weight": 600 });
    val.textContent = b.annotation || fmtPct(b.value);
    svg.appendChild(val);
  });
  return svg;
}

function card(title, settingsLine) {
  const c = el("div", { class: "card" });
  c.appendChild(el("h3", { text: "Computed from the loaded data" }));
  c.appendChild(el("p", { class: "sub", text: title }));
  if (settingsLine) c.appendChild(el("p", { class: "sub", text: "Settings: " + settingsLine }));
  c.appendChild(el("div", { class: "warn note", text: provenanceLine() }));
  return c;
}

/** The sentence that must appear on every result, so no screenshot of this page can be
 *  mistaken for a reported finding. */
function provenanceLine() {
  if (!ORIGIN) return "No data loaded.";
  if (ORIGIN.published) {
    return "PUBLISHED RESEARCH RESULT — recomputed in your browser from the study's "
      + "released outcome data (" + ORIGIN.label + "). Nothing on this card is hard-coded: "
      + "the estimators and the manuscript-cluster bootstrap run here, with the frozen "
      + "generator and seed, and reproduce the published interval endpoints exactly. E0 "
      + "defects are perturbations this study injected into sound published manuscripts.";
  }
  return ORIGIN.synthetic
    ? "SYNTHETIC INPUT — every number below is computed from fabricated demonstration "
      + "data generated by a random number generator (" + ORIGIN.label + "). It is not a "
      + "measurement, not a result of this study, and must not be cited or compared with "
      + "the published paper."
    : "YOUR OWN DATA — computed from the file you loaded in your browser ("
      + ORIGIN.label + "). This site did not supply these numbers and has not transmitted "
      + "your file anywhere. The study's own results are not published in this repository.";
}

function details(summaryText, lines) {
  const d = el("details");
  d.appendChild(el("summary", { text: summaryText }));
  d.appendChild(el("pre", { text: lines.join("\n") }));
  return d;
}

function sel(id, label, options) {
  const wrap = el("div");
  wrap.appendChild(el("label", { for: id, text: label }));
  const s = el("select", { id, name: id });
  for (const o of options) s.appendChild(el("option", { value: o.value, text: o.label }));
  wrap.appendChild(s);
  return wrap;
}

function radios(name, label, options, checked) {
  const wrap = el("div");
  wrap.appendChild(el("label", { text: label, id: name + "-lab" }));
  const g = el("div", { class: "radios", role: "radiogroup",
                        "aria-labelledby": name + "-lab" });
  for (const o of options) {
    const inp = el("input", { type: "radio", name, value: o.value });
    if (o.value === checked) inp.checked = true;
    g.appendChild(el("label", {}, [inp, o.label]));
  }
  wrap.appendChild(g);
  return wrap;
}

/* ---------------------------------------------------------------- settings */

/* The published analysis is over the FIVE open-weight systems. The released table also
 * carries the proprietary replication, so "all systems" is a different population and
 * gives different numbers. That option stays available, but it is never the default:
 * a visitor pressing Run on published data should see the published result. */
const PROPRIETARY = new Set(["gpt-5.2"]);
const openWeightIds = () =>
  DATA.doc.systems.map((s) => s.id).filter((id) => !PROPRIETARY.has(id));
const hasProprietary = () => DATA.doc.systems.some((s) => PROPRIETARY.has(s.id));

function scopeOptions() {
  const out = [];
  if (hasProprietary()) {
    out.push({ value: "openweight",
               label: "Five open-weight systems (the published analysis)" });
    out.push({ value: "all", label: "All systems, including the proprietary replication" });
  } else {
    out.push({ value: "all", label: "All systems pooled" });
  }
  for (const s of DATA.doc.systems) out.push({ value: "sys:" + s.id, label: s.label });
  return out;
}
const scopeSystems = (v) =>
  v === "openweight" ? openWeightIds()
    : v === "all" ? DATA.doc.systems.map((s) => s.id)
    : [v.slice(4)];
function scopeLabel(v) {
  if (v === "openweight") return "five open-weight systems (as published)";
  if (v === "all") return "all systems pooled, including the proprietary replication";
  const s = DATA.doc.systems.find((x) => x.id === v.slice(4));
  return s ? s.label : v;
}

function buildSettings(kind) {
  const box = $("settings");
  box.textContent = "";
  if (!DATA) {
    box.appendChild(el("p", { class: "hint", text: "No data loaded yet." }));
    return;
  }
  if (kind === "ladder") {
    box.appendChild(sel("lscope", "Systems", scopeOptions()));
  }
  if (kind === "table1") {
    box.appendChild(radios("t1metric", "Metric", [
      { value: "balanced_accuracy_pct", label: "Balanced accuracy (pp)" },
      { value: "dprime", label: "d\u2032 (log-linear corrected)" },
    ], "balanced_accuracy_pct"));
    box.appendChild(sel("t1scope", "Systems", scopeOptions()));
    box.appendChild(el("p", { class: "hint", text:
      "Six contrasts \u00d7 two weightings = twelve bootstraps of 10,000 draws each. This "
      + "takes a few seconds; every interval is computed here, not looked up." }));
  }
  if (["experiments", "frontier", "scorer"].includes(kind)) {
    box.appendChild(el("p", { class: "hint", text:
      "This analysis reads the published aggregate files alongside the per-cell table. "
      + "Counts and rates are recomputed from them; where an interval could not be "
      + "recomputed from public data it is labelled as a carried audited aggregate." }));
  }
  if (kind === "contrasts") {
    box.appendChild(sel("cpair", "Contrast", Object.keys(CONTRAST_LABELS)
      .map((k) => ({ value: k, label: CONTRAST_LABELS[k] }))));
    box.appendChild(radios("cmetric", "Metric", [
      { value: "balanced_accuracy_pct", label: "Balanced accuracy (pp)" },
      { value: "dprime", label: "d′ (log-linear corrected)" },
    ], "balanced_accuracy_pct"));
    box.appendChild(radios("cweight", "Weighting", [
      { value: "pooled", label: "Pooled — every eligible cell counts once" },
      { value: "system_balanced", label: "Equal-system — per-system difference, then averaged" },
    ], "pooled"));
    box.appendChild(sel("cscope", "Systems", scopeOptions()));
    box.appendChild(el("p", { class: "hint", text:
      "The interval is a 10,000-draw manuscript-cluster bootstrap, recomputed when you "
      + "press the button." }));
  }
}

/* ---------------------------------------------------------------- the two analyses */

function runLadder() {
  const scope = $("lscope").value;
  const systems = scopeSystems(scope);
  const T = VTBFair.ladderTable(DATA, systems);
  const rungs = DATA.doc.rungs;
  const lab = (r) => (rungs.find((x) => x.id === r) || { label: r }).label;

  const c = card("The four-rung ladder, fairly scored", scopeLabel(scope));

  c.appendChild(el("h3", { text: "What each rung was given, and how it had to answer" }));
  c.appendChild(table(["Rung", "Information exposed", "Response interface"],
    rungs.map((r) => [r.label, r.exposure, r.response_interface])));

  c.appendChild(el("h3", { text: "E0 — the relation is broken" }));
  c.appendChild(table(["Rung", "Detected", "Eligible cells", "Sensitivity"],
    VTBFair.ORDER.map((r) => [lab(r), T[r].hits, T[r].n, fmtPct(T[r].sensitivity_pct)])));

  c.appendChild(el("h3", { text: "E1 — the same relation, exactly as published" }));
  c.appendChild(table(["Rung", "False alarms", "Eligible cells", "False-alarm rate", "Specificity"],
    VTBFair.ORDER.map((r) => [lab(r), T[r].false_alarms, T[r].n,
      fmtPct(T[r].false_alarm_rate_pct), fmtPct(T[r].specificity_pct)])));

  c.appendChild(el("h3", { text: "Both states together" }));
  c.appendChild(table(["Rung", "Balanced accuracy", "d′", "Eligible cells"],
    VTBFair.ORDER.map((r) => [lab(r), fmtPct(T[r].balanced_accuracy_pct),
      fmtD(T[r].dprime), T[r].n])));

  c.appendChild(barChart(VTBFair.ORDER.map((r, i) => ({
    label: RUNG_SHORT[r] || r, value: T[r].balanced_accuracy_pct,
    color: ["#b0453a", "#d9a441", "#2e6b4f", "#2f6690"][i],
  })), { max: 100, alt: "Balanced accuracy by rung" }));

  c.appendChild(el("div", { class: "note", text:
    "These are DESCRIPTIVE MARGINALS: each rung is summarised on its own eligible cells. "
    + "They are not a paired contrast, and the difference between two rows here is not the "
    + "paired difference between those rungs. Use the contrast analysis for that." }));

  c.appendChild(details("How was this calculated?", [
    "Aggregation level: one row = one (system, rung, relation) cell, pooled over the",
    "systems in the chosen scope. A cell counts only if the response was scoreable in",
    "BOTH evidence states.",
    "",
    ...VTBFair.ORDER.map((r) =>
      `${r.padEnd(9)} n=${T[r].n}  hits=${T[r].hits}  false alarms=${T[r].false_alarms}`),
    "",
    "sensitivity       = hits / n",
    "false-alarm rate  = false alarms / n     (tested relation only; a finding about",
    "                                          anything else counts neither way)",
    "specificity       = 1 - false-alarm rate",
    "balanced accuracy = (sensitivity + specificity) / 2",
    "d'                = z(hit rate) - z(false-alarm rate), Hautus (1995) log-linear",
    "                    correction: +0.5 to each count, +1.0 to each total, applied",
    "                    unconditionally.",
    "",
    ...VTBFair.ORDER.map((r) =>
      `${r.padEnd(9)} balacc = (${T[r].hits}/${T[r].n} + 1 - ${T[r].false_alarms}/${T[r].n}) / 2`
      + ` = ${T[r].balanced_accuracy_pct.toFixed(3)}%   d' = ${T[r].dprime.toFixed(4)}`),
    "",
    "Input: " + ORIGIN.label,
    ORIGIN.synthetic ? "  SYNTHETIC - generated by tools/make_synthetic_demo.py, not measured."
                     : ORIGIN.published
                       ? "  PUBLISHED - the study's released per-cell outcomes, recomputed here."
                       : "  Loaded from your computer; not supplied or transmitted by this site.",
  ]));
  return c;
}

function runContrasts() {
  const key = $("cpair").value;
  const [a, b] = key.split("->");
  const metric = document.querySelector('input[name="cmetric"]:checked').value;
  const weighting = document.querySelector('input[name="cweight"]:checked').value;
  const scope = $("cscope").value;
  const systems = scopeSystems(scope);

  const r = VTBFair.contrast(DATA, a, b, systems, weighting, metric);
  if (!r.n_cells) {
    const c = card(CONTRAST_LABELS[key], scopeLabel(scope));
    c.appendChild(el("p", { class: "sub", text:
      "No cell is eligible for this contrast in the loaded data: no relation has a "
      + "scoreable response at both rungs in both evidence states." }));
    return c;
  }
  const other = VTBFair.contrast(DATA, a, b, systems,
    weighting === "pooled" ? "system_balanced" : "pooled", metric);
  const unit = metric === "dprime" ? "" : " pp";
  const lab = (x) => (DATA.doc.rungs.find((y) => y.id === x) || { label: x }).label;

  const c = card(CONTRAST_LABELS[key], `${scopeLabel(scope)} · ${METRIC_LABEL[metric]}`
    + ` · ${weighting === "pooled" ? "pooled" : "equal-system"} weighting`);

  c.appendChild(el("p", { class: "headline "
    + (r.excludesZero ? (r.point >= 0 ? "pos" : "neg") : ""), text: fmt3(r.point) + unit }));
  c.appendChild(el("p", { class: "sub", text:
    `95% manuscript-cluster bootstrap CI [${fmt3(r.lo)}, ${fmt3(r.hi)}]${unit} · `
    + `${r.n_cells} complete-case cells · ${r.n_clusters} clusters` }));

  c.appendChild(el("div", { class: r.excludesZero ? "note" : "warn note", text:
    r.excludesZero
      ? "The interval excludes zero. In this dataset a difference in this direction is "
        + "established at the 95% level."
      : "⚠ THE INTERVAL INCLUDES ZERO. Nothing is established by this contrast in this "
        + "dataset. It must not be described as an improvement, however large the point "
        + "estimate looks." }));

  c.appendChild(table(["Rung", "Detected (E0)", "False alarms (E1)", "Cells",
                       "Sensitivity", "Specificity", "Balanced accuracy", "d′"], [
    [lab(a), r.A.hits, r.A.false_alarms, r.A.n, fmtPct(r.A.sensitivity_pct),
     fmtPct(r.A.specificity_pct), fmtPct(r.A.balanced_accuracy_pct), fmtD(r.A.dprime)],
    [lab(b), r.B.hits, r.B.false_alarms, r.B.n, fmtPct(r.B.sensitivity_pct),
     fmtPct(r.B.specificity_pct), fmtPct(r.B.balanced_accuracy_pct), fmtD(r.B.dprime)],
  ]));

  const flip = (r.point >= 0) !== (other.point >= 0);
  const signif = r.excludesZero !== other.excludesZero;
  c.appendChild(el("h3", { text: "The same contrast under the other weighting" }));
  c.appendChild(table(["Weighting", "Estimate", "95% CI", "Excludes zero?"], [
    [weighting === "pooled" ? "pooled (this result)" : "equal-system (this result)",
     fmt3(r.point) + unit, `[${fmt3(r.lo)}, ${fmt3(r.hi)}]`, r.excludesZero ? "yes" : "no"],
    [weighting === "pooled" ? "equal-system" : "pooled",
     fmt3(other.point) + unit, `[${fmt3(other.lo)}, ${fmt3(other.hi)}]`,
     other.excludesZero ? "yes" : "no"],
  ]));
  if (flip || signif) {
    c.appendChild(el("div", { class: "warn note", text:
      "⚠ THIS CONTRAST IS WEIGHTING-DEPENDENT IN THIS DATASET. "
      + (flip ? "The two weightings disagree about the SIGN of the effect. " : "")
      + (signif ? "They disagree about whether the interval excludes zero. " : "")
      + "It cannot be reported without naming the weighting." }));
  } else {
    c.appendChild(el("p", { class: "hint", text:
      "The two weightings agree in sign and in whether the interval excludes zero." }));
  }

  c.appendChild(barChart([
    { label: RUNG_SHORT[a] || a,
      value: metric === "dprime" ? r.A.dprime : r.A.balanced_accuracy_pct, color: "#b0453a",
      annotation: metric === "dprime" ? fmtD(r.A.dprime) : fmtPct(r.A.balanced_accuracy_pct) },
    { label: RUNG_SHORT[b] || b,
      value: metric === "dprime" ? r.B.dprime : r.B.balanced_accuracy_pct, color: "#2f6690",
      annotation: metric === "dprime" ? fmtD(r.B.dprime) : fmtPct(r.B.balanced_accuracy_pct) },
  ], { max: metric === "dprime" ? 3 : 100, unit: metric === "dprime" ? "d" : "pct",
       alt: "Rung A against rung B on the chosen metric" }));

  c.appendChild(details("How was this calculated?", [
    `Contrast: ${a} -> ${b}.  Metric: ${METRIC_LABEL[metric]}.  Weighting: ${weighting}.`,
    "",
    "ELIGIBILITY (complete-case pairing)",
    "  A (system, relation) cell enters only if BOTH rungs produced a scoreable response",
    "  in BOTH evidence states. A cell missing on either side is dropped from both, so the",
    "  two rungs are always compared on identical cells.",
    `  eligible cells = ${r.n_cells}   systems = ${r.n_systems}   clusters = ${r.n_clusters}`,
    "",
    "RUNG MARGINALS ON THAT SET",
    `  ${a.padEnd(9)} hits=${r.A.hits}/${r.A.n}  false alarms=${r.A.false_alarms}/${r.A.n}`
      + `  balacc=${r.A.balanced_accuracy_pct.toFixed(3)}%  d'=${r.A.dprime.toFixed(4)}`,
    `  ${b.padEnd(9)} hits=${r.B.hits}/${r.B.n}  false alarms=${r.B.false_alarms}/${r.B.n}`
      + `  balacc=${r.B.balanced_accuracy_pct.toFixed(3)}%  d'=${r.B.dprime.toFixed(4)}`,
    "",
    "ESTIMAND",
    weighting === "pooled"
      ? "  pooled: metric(B) - metric(A), every eligible cell counting once."
      : "  equal-system: the per-system difference first, then an unweighted mean over\n"
        + "  systems.",
    `  point estimate = ${r.point.toFixed(6)}${unit}`,
    "",
    "INTERVAL",
    "  Manuscript-cluster bootstrap: clusters are the resampling unit, because relations",
    "  within one manuscript are not independent. The WHOLE estimand is recomputed inside",
    "  each replicate; rates are never themselves resampled.",
    `  draws = ${r.draws}   replicates used = ${r.draws_used}   seed = ${r.seed}   PRNG = mulberry32`,
    `  95% CI = [2.5th, 97.5th] percentile = [${r.lo.toFixed(6)}, ${r.hi.toFixed(6)}]${unit}`,
    `  excludes zero: ${r.excludesZero ? "yes" : "NO - nothing is established"}`,
    "",
    "  mulberry32 is used so that this browser and src/analysis/fair_contrasts.py produce",
    "  bit-identical intervals, which the repository's tests assert.",
    "",
    "Input: " + ORIGIN.label,
    ORIGIN.synthetic ? "  SYNTHETIC - generated by tools/make_synthetic_demo.py, not measured."
                     : ORIGIN.published
                       ? "  PUBLISHED - the study's released per-cell outcomes, recomputed here."
                       : "  Loaded from your computer; not supplied or transmitted by this site.",
  ]));
  return c;
}


/* ----------------------------------------------- published-data analyses */

/** Require a published aggregate block, and say plainly which one is missing. */
function need(block, name) {
  if (!block) {
    throw new Error("This analysis needs docs/data/" + name + ", which did not load. "
      + "Select 'Published research results' as the data source.");
  }
  return block;
}

const pp = (v) => (Number.isFinite(v) ? (v >= 0 ? "+" : "\u2212") + Math.abs(v).toFixed(2) : "n/a");
const ci = (lo, hi) => "[" + pp(lo) + ", " + pp(hi) + "]";

/** All six contrasts, both weightings, side by side. Sign and significance flips are the
 *  point of the table, so they are marked rather than left for the reader to spot. */
function runTable1() {
  const systems = scopeSystems($("t1scope") ? $("t1scope").value : "all");
  const metric = document.querySelector('input[name="t1metric"]:checked').value;
  const unit = metric === "dprime" ? "" : " pp";
  const c = card("All six paired contrasts",
    scopeLabel($("t1scope") ? $("t1scope").value : "all") + " \u00b7 " + METRIC_LABEL[metric]
    + " \u00b7 both weightings");
  const rows = [];
  let flips = 0;
  for (const spec of VTBFair.CONTRASTS) {
    const key = spec.id || spec.key || (spec.a + "->" + spec.b);
    const a = spec.a || key.split("->")[0], b = spec.b || key.split("->")[1];
    const P = VTBFair.contrast(DATA, a, b, systems, "pooled", metric);
    const B = VTBFair.contrast(DATA, a, b, systems, "system_balanced", metric);
    const signFlip = (P.point >= 0) !== (B.point >= 0);
    const sigFlip = P.excludesZero !== B.excludesZero;
    if (signFlip || sigFlip) flips++;
    rows.push([
      CONTRAST_LABELS[key] || key, P.n_cells,
      pp(P.point) + unit, ci(P.lo, P.hi), P.excludesZero ? "yes" : "NO",
      pp(B.point) + unit, ci(B.lo, B.hi), B.excludesZero ? "yes" : "NO",
      signFlip ? "sign" : (sigFlip ? "significance" : "\u2014"),
    ]);
  }
  c.appendChild(table(["Contrast", "Paired n", "Pooled", "95% CI", "Excl. 0?",
    "Equal-system", "95% CI", "Excl. 0?", "Disagrees?"], rows));
  c.appendChild(el("div", { class: flips ? "warn note" : "note", text: flips
    ? "\u26a0 " + flips + " of the six contrasts DISAGREE between the two weightings, in "
      + "sign or in whether the interval excludes zero. Pooled and equal-system are "
      + "different estimands. Quoting whichever is significant would misreport the study."
    : "The two weightings agree on all six contrasts." }));
  c.appendChild(details("How this was computed", [
    "estimand:   difference between two rungs on the complete-case paired set",
    "pairing:    a cell enters only if BOTH rungs are scoreable in BOTH states",
    "bootstrap:  manuscript-cluster, " + VTBFair.DRAWS + " draws, seed " + VTBFair.SEED,
    "generator:  CPython Mersenne Twister (assets/mt19937.js) - the frozen generator,",
    "            so these interval endpoints are the published endpoints, not near ones",
    "d-prime:    log-linear corrected, +0.5 per count and +1.0 per total, unconditionally",
  ]));
  return c;
}

/** Findings that are not rung contrasts: the broader benchmark, the three evidence
 *  states, bounded agentic navigation, and what transfers between verifiers. */
function runExperiments() {
  const S = need(STATS, "public_sufficient_statistics.json").experiments;
  const R = need(RESEARCH, "research_results.json");
  const c = card("Other published findings", "recomputed from released counts");

  const dv = S.discovery_vs_localized.pooled;
  c.appendChild(el("h3", { text: "Blind discovery against relation-localized verification" }));
  c.appendChild(table(["Condition", "Correct", "n", "Rate"], [
    ["Blind discovery", dv.blind.x, dv.blind.n, fmtPct(100 * dv.blind.x / dv.blind.n)],
    ["Relation-localized", dv.targeted.x, dv.targeted.n,
     fmtPct(100 * dv.targeted.x / dv.targeted.n)],
    ["Difference", "\u2014", dv.n,
     pp(100 * (dv.targeted.x - dv.blind.x) / dv.blind.n) + " pp"],
  ]));

  const t = R.three_state_localized;
  c.appendChild(el("h3", { text: "The same relation in three evidence states" }));
  c.appendChild(table(["State", "Correct", "n", "Rate"], [
    ["E0 \u2014 relation broken", t.E0_defective.x, t.E0_defective.n,
     fmtPct(100 * t.E0_defective.x / t.E0_defective.n)],
    ["E1 \u2014 as published", t.E1_as_published.x, t.E1_as_published.n,
     fmtPct(100 * t.E1_as_published.x / t.E1_as_published.n)],
    ["E2 \u2014 alternate perturbation", t.E2_alternate.x, t.E2_alternate.n,
     fmtPct(100 * t.E2_alternate.x / t.E2_alternate.n)],
    ["Correct in all three", t.correct_in_all_three.x, t.correct_in_all_three.n,
     fmtPct(100 * t.correct_in_all_three.x / t.correct_in_all_three.n)],
  ]));
  c.appendChild(el("div", { class: "warn note", text:
    t.cited_relation_but_wrong_verdict + " trials cited the tested relation and still "
    + "returned the wrong verdict. Citing the right evidence is not the same as verifying "
    + "it. Denominators differ between states because scoreability is judged per state." }));

  const ag = S.agentic;
  c.appendChild(el("h3", { text: "Bounded agentic navigation" }));
  c.appendChild(table(["Condition", "Found", "n", "Rate"], [
    ["Direct blind", ag.direct_blind.x, ag.direct_blind.n,
     fmtPct(100 * ag.direct_blind.x / ag.direct_blind.n)],
    ["Agentic blind", ag.agentic_blind.x, ag.agentic_blind.n,
     fmtPct(100 * ag.agentic_blind.x / ag.agentic_blind.n)],
    ["Paired difference", "\u2014", ag.n_paired_cases,
     pp(100 * (ag.agentic_blind.x - ag.direct_blind.x) / ag.n_paired_cases) + " pp"],
  ]));
  c.appendChild(el("p", { class: "sub", text: ag.scope_note }));

  const tf = S.information_transfer;
  c.appendChild(el("h3", { text: "What transfers between verifiers" }));
  const trows = [];
  for (const k of Object.keys(tf.frozen_contrasts)) {
    const f = tf.frozen_contrasts[k];
    trows.push([f.question, f.n, pp(100 * (f.b - f.c) / f.n) + " pp",
      f.frozen_ci95_pp ? ci(f.frozen_ci95_pp[0], f.frozen_ci95_pp[1]) : "n/a"]);
  }
  c.appendChild(table(["Contrast", "Paired n", "Difference", "95% CI (frozen)"], trows));
  c.appendChild(details("How this was computed", [
    "paired contrasts use the discordant cells: (b - c) / n, NOT a difference of two",
    "independent arm rates, which would ignore the pairing and misstate the interval",
    "confidence intervals shown here are the frozen analysis's own, carried as published",
    "aggregates; the point estimates are recomputed from the released counts",
  ]));
  return c;
}

/** The proprietary replications, with their refusal accounting shown rather than buried. */
function runFrontier() {
  const F = need(RESEARCH, "research_results.json").frontier;
  const c = card("Proprietary systems", "GPT\u20115.2 and Claude Sonnet 5.5");
  c.appendChild(el("h3", { text: "GPT\u20115.2" }));
  const o = F.openai || {};
  const rows = [];
  const walk = (obj, prefix) => {
    for (const k of Object.keys(obj || {})) {
      const v = obj[k];
      if (v && typeof v === "object" && !Array.isArray(v)) walk(v, prefix ? prefix + " / " + k : k);
      else rows.push([(prefix ? prefix + " / " : "") + k, String(v)]);
    }
  };
  walk(o, "");
  c.appendChild(table(["Field", "Value"], rows.slice(0, 40)));

  const a = F.anthropic;
  c.appendChild(el("h3", { text: "Claude Sonnet 5.5" }));
  const acc = a.accuracy.primary_strict_parser;
  c.appendChild(table(["Quantity", "Value"], [
    ["Strictly parsed verdicts", acc.n_scored],
    ["Correct", acc.n_correct],
    ["Accuracy on strictly parsed verdicts", fmtPct(acc.accuracy_pct)],
    ["Of the 60 scoreable cases", acc.n_of_60_scoreable],
  ]));
  c.appendChild(el("div", { class: "warn note", text: a.refusals_are_not_errors
    + " The finding-list rungs were refused outright, so there is no finding-list score "
    + "for this system at all. A denominator of " + acc.n_scored + " is not a denominator "
    + "of 60, and treating refusals as wrong answers would invent a result." }));
  c.appendChild(details("Output accounting", Object.keys(a.binary_verdict_rung.categories
    || a.binary_verdict_rung).map((k) => "  " + k + ": "
    + JSON.stringify((a.binary_verdict_rung.categories || a.binary_verdict_rung)[k]))));
  return c;
}

/** The human scorer audits, and the four correction scenarios kept distinct. */
function runScorer() {
  const A = need(AUDIT, "scorer_audit_items.json");
  const R = need(RESEARCH, "research_results.json").scorer_correction_scenarios;
  const c = card("Human scorer audits", "per-item rating counts, recomputed here");

  const LV = ["Yes", "Partially", "No", "Ambiguous / Cannot determine"];
  const summarise = (aud) => {
    const tot = { Yes: 0, Partially: 0, No: 0, "Ambiguous / Cannot determine": 0 };
    let unanimous = 0;
    for (const it of aud.items) {
      let mx = 0;
      for (const k of LV) { tot[k] += it.counts[k] || 0; mx = Math.max(mx, it.counts[k] || 0); }
      if (mx === it.n_reviewers) unanimous++;
    }
    const n = LV.reduce((s, k) => s + tot[k], 0);
    return { tot, n, unanimous };
  };
  for (const [key, title] of [["targeted", "Relation-targeted scorer audit"],
                              ["blind", "Blind scorer audit"]]) {
    const aud = A.audits[key];
    const s = summarise(aud);
    c.appendChild(el("h3", { text: title }));
    c.appendChild(table(["Quantity", "Value"], [
      ["Items", aud.n_items], ["Reviewers", aud.n_reviewers], ["Judgments", s.n],
      ["Scorer endorsed (No)", s.tot.No + " of " + s.n + " = " + fmtPct(100 * s.tot.No / s.n)],
      ["Scorer false negative (Yes)", s.tot.Yes + " of " + s.n + " = "
        + fmtPct(100 * s.tot.Yes / s.n)],
      ["Unanimous items", s.unanimous + " of " + aud.n_items],
    ]));
    if (key === "targeted") {
      const st = {};
      for (const it of aud.items) {
        const k = it.stratum;
        st[k] = st[k] || { yes: 0, n: 0, pop: it.stratum_population };
        st[k].n++;
        let mx = 0, arg = null;
        for (const L of LV) if ((it.counts[L] || 0) > mx) { mx = it.counts[L]; arg = L; }
        if (arg === "Yes") st[k].yes++;
      }
      let num = 0, den = 0;
      const srows = Object.keys(st).sort().map((k) => {
        num += st[k].pop * st[k].yes / st[k].n; den += st[k].pop;
        return [k, st[k].yes + "/" + st[k].n, st[k].pop,
          fmtPct(100 * st[k].yes / st[k].n)];
      });
      c.appendChild(table(["Stratum", "Majority-Yes items", "Population", "Rate"], srows));
      c.appendChild(el("p", { class: "sub", text:
        "Population-reweighted false-negative rate: " + fmtPct(100 * num / den)
        + " across " + den + " corpus misses \u2014 recomputed here from the per-item "
        + "counts above, not quoted." }));
    }
  }
  c.appendChild(el("h3", { text: "Correction scenarios \u2014 four, not one" }));
  const sc = R.scenarios;
  c.appendChild(table(["Scenario", "Balanced accuracy", "95% CI", "d\u2032", "d\u2032 95% CI",
                       "d\u2032 excludes 0?"],
    Object.keys(sc).map((k) => [k,
      pp(sc[k].balanced_accuracy_difference_pp) + " pp",
      ci(sc[k].balanced_accuracy_ci95[0], sc[k].balanced_accuracy_ci95[1]),
      pp(sc[k].dprime_difference),
      ci(sc[k].dprime_ci95[0], sc[k].dprime_ci95[1]),
      sc[k].dprime_difference_excludes_zero ? "yes" : "NO"])));
  c.appendChild(el("div", { class: "warn note", text: R.symmetric_scenarios_are_modelled }));
  const w = R.which_scenario_the_manuscript_quotes;
  c.appendChild(el("div", { class: "note", text:
    "The manuscript's conservative one-sided figure is the scenario named '"
    + w.conservative_one_sided + "'. " + w.why + " An earlier public aggregate reported '"
    + w.earlier_public_aggregate_used + "' instead. They are different scenarios, not a "
    + "contradiction." }));
  c.appendChild(el("div", { class: "warn note", text:
    "This audit is of the SCORER, not of any person. Only per-item rating counts are "
    + "published: the reviewer axis and all free text are withheld, so reviewer-level "
    + "agreement cannot be recomputed here and is carried as an audited aggregate." }));
  return c;
}

const RUNNERS = { ladder: runLadder, contrasts: runContrasts,
  table1: runTable1, experiments: runExperiments,
  frontier: runFrontier, scorer: runScorer };

/* ---------------------------------------------------------------- data loading */

function adopt(doc, label, synthetic, published) {
  const problems = [];
  for (const k of ["fields", "cells", "systems", "rungs"]) {
    if (!doc || !doc[k]) problems.push("missing '" + k + "'");
  }
  if (problems.length) throw new Error("not a cell table: " + problems.join(", "));
  DATA = VTBFair.parse(doc);
  ORIGIN = {
    label,
    synthetic: synthetic === undefined ? !!doc.synthetic : synthetic,
    published: published === true,
  };
  $("data-status").textContent =
    `Loaded ${doc.cells.length} cells, ${doc.systems.length} systems, `
    + `${doc.rungs.length} rungs — `
    + (ORIGIN.published ? "published research data"
       : ORIGIN.synthetic ? "synthetic" : "your file") + ".";
  buildSettings($("experiment").value);
  $("run").disabled = false;
}

/** The study's released outcome data, plus the aggregate blocks that go with it. */
let SUPPORT = null, RESEARCH = null, AUDIT = null, STATS = null;

async function getJSON(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(path + ": HTTP " + res.status);
  return res.json();
}

async function loadPublished() {
  const doc = await getJSON("data/fair_scoring_cells.json");
  [SUPPORT, RESEARCH, AUDIT, STATS] = await Promise.all([
    getJSON("data/fair_scoring_support.json").catch(() => null),
    getJSON("data/research_results.json").catch(() => null),
    getJSON("data/scorer_audit_items.json").catch(() => null),
    getJSON("data/public_sufficient_statistics.json").catch(() => null),
  ]);
  adopt(doc, "docs/data/fair_scoring_cells.json — " + doc.cells.length
    + " released per-cell outcomes", false, true);
}

async function loadSynthetic() {
  const res = await fetch("data/synthetic_demo_cells.json", { cache: "no-store" });
  if (!res.ok) throw new Error("HTTP " + res.status);
  const doc = await res.json();
  adopt(doc, "docs/data/synthetic_demo_cells.json (synthetic fixture, seed "
    + doc.seed + ")", true);
}

function wireUpload() {
  $("userfile").addEventListener("change", (ev) => {
    const f = ev.target.files && ev.target.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      reset();
      try {
        adopt(JSON.parse(reader.result), f.name, false);
      } catch (e) {
        DATA = null; ORIGIN = null;
        $("run").disabled = true;
        $("data-status").textContent = "Could not read that file: "
          + (e && e.message ? e.message : e);
      }
    };
    reader.onerror = () => {
      $("data-status").textContent = "Could not read that file.";
    };
    reader.readAsText(f);
  });
}

/* ---------------------------------------------------------------- wiring */

function reset() {
  $("output").textContent = "";
  $("reset").disabled = true;
  $("status").textContent = "";
}

async function init() {
  const expSel = $("experiment");
  const dsSel = $("datasource");
  const setHint = () => { $("experiment-hint").textContent = HINTS[expSel.value] || ""; };

  wireUpload();
  setHint();
  /* Analyses that read the published aggregate blocks only make sense on published data. */
  const gate = () => {
    const pub = dsSel.value === "published";
    for (const o of expSel.options) {
      const needsPublished = ["table1", "experiments", "frontier", "scorer"].includes(o.value);
      o.disabled = needsPublished && !pub;
    }
    if (expSel.selectedOptions[0] && expSel.selectedOptions[0].disabled) {
      expSel.value = "ladder"; setHint(); buildSettings("ladder");
    }
  };
  dsSel.addEventListener("change", gate);
  gate();

  const loadFor = async (kind) => {
    try {
      if (kind === "published") await loadPublished();
      else await loadSynthetic();
    } catch (e) {
      $("data-status").textContent =
        "Could not load the " + (kind === "published" ? "published research data"
          : "synthetic fixture") + " (" + e.message + "). If you opened this page from the "
        + "filesystem, serve it over HTTP instead: python -m http.server. You can still "
        + "load a file of your own.";
      $("run").disabled = true;
    }
  };

  dsSel.addEventListener("change", async () => {
    reset();
    const upload = dsSel.value === "upload";
    $("upload-box").hidden = !upload;
    if (upload) {
      DATA = null; ORIGIN = null;
      $("run").disabled = true;
      $("data-status").textContent = "Choose a JSON cell table from your computer.";
      $("settings").textContent = "";
    } else {
      await loadFor(dsSel.value);
    }
  });

  expSel.addEventListener("change", () => { buildSettings(expSel.value); setHint(); reset(); });

  $("controls").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const out = $("output");
    out.textContent = "";
    if (!DATA) {
      out.appendChild(el("div", { class: "card" }, [
        el("h3", { text: "No data loaded" }),
        el("p", { class: "sub", text: "Choose the synthetic fixture or load a file first." }),
      ]));
      $("reset").disabled = false;
      return;
    }
    let node;
    try {
      node = RUNNERS[expSel.value]();
    } catch (e) {
      node = el("div", { class: "card" }, [
        el("h3", { text: "Could not run the analysis" }),
        el("p", { class: "sub", text: String(e && e.message ? e.message : e) }),
      ]);
    }
    out.appendChild(node);
    $("reset").disabled = false;
    $("status").textContent = "Computed in your browser.";
    node.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  $("reset").addEventListener("click", reset);

  await loadFor(dsSel.value);
  gate();
}

document.addEventListener("DOMContentLoaded", init);
