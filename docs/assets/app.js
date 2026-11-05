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

function scopeOptions() {
  const out = [{ value: "all", label: "All systems pooled" }];
  for (const s of DATA.doc.systems) out.push({ value: "sys:" + s.id, label: s.label });
  return out;
}
const scopeSystems = (v) =>
  v === "all" ? DATA.doc.systems.map((s) => s.id) : [v.slice(4)];
function scopeLabel(v) {
  if (v === "all") return "all systems pooled";
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
                     : "  Loaded from your computer; not supplied or transmitted by this site.",
  ]));
  return c;
}

const RUNNERS = { ladder: runLadder, contrasts: runContrasts };

/* ---------------------------------------------------------------- data loading */

function adopt(doc, label, synthetic) {
  const problems = [];
  for (const k of ["fields", "cells", "systems", "rungs"]) {
    if (!doc || !doc[k]) problems.push("missing '" + k + "'");
  }
  if (problems.length) throw new Error("not a cell table: " + problems.join(", "));
  DATA = VTBFair.parse(doc);
  ORIGIN = { label, synthetic: synthetic === undefined ? !!doc.synthetic : synthetic };
  $("data-status").textContent =
    `Loaded ${doc.cells.length} cells, ${doc.systems.length} systems, `
    + `${doc.rungs.length} rungs — ${ORIGIN.synthetic ? "synthetic" : "your file"}.`;
  buildSettings($("experiment").value);
  $("run").disabled = false;
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

  const useSynthetic = async () => {
    try {
      await loadSynthetic();
    } catch (e) {
      $("data-status").textContent =
        "Could not load the synthetic fixture (" + e.message + "). If you opened this page "
        + "from the filesystem, serve it over HTTP instead: python -m http.server. You can "
        + "still load a file of your own.";
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
      await useSynthetic();
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

  await useSynthetic();
}

document.addEventListener("DOMContentLoaded", init);
