/* VerifierTrustBench playground.
   No result value and no chart exists in the DOM until the visitor presses "Reproduce result".
   Everything is computed here, in the browser, from docs/data/public_sufficient_statistics.json. */
"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, kids = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(kids)) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  return n;
};
const svgEl = (tag, attrs = {}) => {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};

let DATA = null;

/* ---------------------------------------------------------------- statistics */

const pct = (x, n) => (n ? (100 * x) / n : NaN);
const fmtPct = (v) => (Number.isFinite(v) ? v.toFixed(1) + "%" : "n/a");
const fmtPP = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1) + " pp";

/** Exact two-sided McNemar p from the discordant counts, in exact integer arithmetic.
 *  p = min(1, 2 * sum_{i<=k} C(n,i) / 2^n) with n = b + c, k = min(b, c). */
function exactMcNemar(b, c) {
  const n = b + c;
  if (n === 0) return 1;
  const k = BigInt(Math.min(b, c));
  const N = BigInt(n);
  let comb = 1n, sum = 0n;
  for (let i = 0n; i <= k; i++) {
    if (i > 0n) comb = (comb * (N - i + 1n)) / i;
    sum += comb;
  }
  const num = 2n * sum, den = 1n << N;
  if (num >= den) return 1;
  // Ratio of two big integers to a double. A fixed scale underflows for the large-n
  // contrasts (2^909 vs a p around 1e-63), so scale by the bit-length difference:
  // shift the numerator until the quotient lands near 2^64, then undo the shift.
  const bits = (x) => x.toString(2).length;
  const shift = BigInt(Math.max(0, bits(den) - bits(num) + 64));
  const scaled = Number((num << shift) / den);
  const out = scaled * Math.pow(2, -Number(shift));
  return Number.isFinite(out) ? out : 0;
}

const fmtP = (p) => {
  if (!Number.isFinite(p)) return "n/a";
  if (p >= 0.1) return "p = " + p.toFixed(2);
  if (p >= 1e-4) return "p = " + p.toPrecision(2);
  if (p === 0) return "p < 1e-300";
  const e = Math.floor(Math.log10(p));
  return "p = " + (p / 10 ** e).toFixed(2) + "×10" + sup(e);
};
const sup = (n) => String(n).replace(/-/g, "⁻").replace(/[0-9]/g, (d) => "⁰¹²³⁴⁵⁶⁷⁸⁹"[+d]);

/** Newcombe method-10 interval for a paired difference of proportions, in pp. */
function pairedCI(both, b, c, neither) {
  const n = both + b + c + neither;
  if (!n) return [NaN, NaN];
  const p1 = (both + b) / n, p2 = (both + c) / n, d = p1 - p2;
  const w = (x) => {
    const z = 1.959963984540054, p = x / n, z2 = z * z;
    const centre = (p + z2 / (2 * n)) / (1 + z2 / n);
    const half = (z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / (1 + z2 / n);
    return [centre - half, centre + half];
  };
  const [l1, u1] = w(both + b), [l2, u2] = w(both + c);
  const A = both, B = b, C = c, D = neither;
  const denom = Math.sqrt((A + B) * (C + D) * (A + C) * (B + D));
  const phi = denom > 0 ? (A * D - B * C) / denom : 0;
  const lo = d - Math.sqrt((p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2);
  const hi = d + Math.sqrt((u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2);
  return [100 * lo, 100 * hi];
}

/* ---------------------------------------------------------------- settings UI */

const HINTS = {
  discovery: "The same relations, judged twice: once with nothing pointed at, once with the relation named.",
  ranking: "If a blind system missed a defect, was it surfaced but ranked low? Extend the finding list and see.",
  agentic: "Give one system a bounded budget of navigation tool calls and re-run blind discovery.",
  transfer: "Hold length fixed and vary what an upstream verifier passes downstream.",
  profile: "Assemble the full profile for a single system. Nothing is averaged into one score.",
};

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
  const g = el("div", { class: "radios", role: "radiogroup", "aria-labelledby": name + "-lab" });
  for (const o of options) {
    const inp = el("input", { type: "radio", name, value: o.value });
    if (o.value === checked) inp.checked = true;
    g.appendChild(el("label", {}, [inp, o.label]));
  }
  wrap.appendChild(g);
  return wrap;
}

function modelOptions() {
  return DATA.models.map((m) => ({ value: m.id, label: m.label }));
}

function buildSettings(kind) {
  const box = $("settings");
  box.textContent = "";
  const E = DATA.experiments;

  if (kind === "discovery") {
    const strata = [{ value: "pooled", label: "All systems pooled" }];
    for (const m of DATA.models) strata.push({ value: "model:" + m.id, label: "System — " + m.label });
    for (const f of Object.keys(E.discovery_vs_localized.by_family))
      strata.push({ value: "family:" + f, label: "Defect family — " + f.replace(/_/g, " ") });
    for (const d of Object.keys(E.discovery_vs_localized.by_domain))
      strata.push({ value: "domain:" + d, label: "Domain — " + (E.discovery_vs_localized.domain_labels[d] || d) });
    box.appendChild(sel("stratum", "Slice of the paired data", strata));
    box.appendChild(el("p", { class: "hint", text:
      "Slices are precomputed strata, so cross-reference relations can be isolated by picking that family — but slices cannot be combined or subtracted from one another." }));
  }

  if (kind === "ranking") {
    box.appendChild(sel("rmodel", "System", modelOptions()));
    const ks = E.ranking.ks_observable.map((k) => ({ value: String(k), label: "k = " + k }));
    box.appendChild(radios("k", "Finding budget k", ks, "1"));
    box.appendChild(el("p", { class: "hint", text: E.ranking.budget_note }));
  }

  if (kind === "agentic") {
    box.appendChild(radios("conds", "Conditions to compare", [
      { value: "direct_vs_agentic", label: "Direct blind vs bounded agentic" },
      { value: "agentic_vs_localized", label: "Bounded agentic vs relation-localized" },
      { value: "all_three", label: "All three conditions" },
    ], "direct_vs_agentic"));
    box.appendChild(el("p", { class: "hint", text:
      "System: " + (DATA.models.find((m) => m.id === E.agentic.model) || {}).label +
      ". " + E.agentic.scope_note }));
  }

  if (kind === "transfer") {
    const arms = Object.keys(E.information_transfer.arms)
      .map((a) => ({ value: a, label: E.information_transfer.arm_labels[a] || a }));
    box.appendChild(sel("armA", "Condition A", arms));
    box.appendChild(sel("armB", "Condition B", arms));
    setTimeout(() => { $("armA").value = "correct_rationale"; $("armB").value = "cv_irrelevant"; }, 0);
    box.appendChild(el("p", { class: "hint", text:
      "Unpaired arm rates are always available. Where the chosen pair matches a frozen paired contrast, the paired cell counts, interval and exact p are shown too." }));
  }

  if (kind === "profile") {
    box.appendChild(sel("pmodel", "System", modelOptions()));
    box.appendChild(el("p", { class: "hint", text:
      "Produces the four profile components the public aggregates support: discovery, evidence responsiveness, provenance and specificity." }));
  }
}

/* ---------------------------------------------------------------- charts (built on demand) */

function barChart(bars, opts = {}) {
  const W = 640, rowH = 46, padL = 190, padR = 70, padT = 14;
  const H = padT + bars.length * rowH + 14;
  const max = opts.max || Math.max(100, ...bars.map((b) => b.value));
  const svg = svgEl("svg", {
    viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": opts.alt || "Bar chart of the reproduced values",
  });
  const scale = (v) => ((W - padL - padR) * v) / max;
  for (const t of [0, 25, 50, 75, 100]) {
    if (t > max) continue;
    const x = padL + scale(t);
    svg.appendChild(svgEl("line", { x1: x, y1: padT, x2: x, y2: H - 20,
      stroke: "currentColor", "stroke-opacity": t === 0 ? 0.45 : 0.14 }));
    const lab = svgEl("text", { x, y: H - 6, "text-anchor": "middle", "font-size": 11, "fill-opacity": 0.6 });
    lab.textContent = t + "%";
    svg.appendChild(lab);
  }
  bars.forEach((b, i) => {
    const y = padT + i * rowH + 8;
    const name = svgEl("text", { x: padL - 10, y: y + 16, "text-anchor": "end", "font-size": 12.5 });
    name.textContent = b.label;
    svg.appendChild(name);
    svg.appendChild(svgEl("rect", { x: padL, y, width: Math.max(1, scale(b.value)), height: 24,
      rx: 3, fill: b.color || "#2f6690" }));
    const val = svgEl("text", { x: padL + scale(b.value) + 8, y: y + 17, "font-size": 12.5, "font-weight": 600 });
    val.textContent = b.annotation || fmtPct(b.value);
    svg.appendChild(val);
  });
  return svg;
}

function lineChart(series, xs, opts = {}) {
  const W = 640, H = 300, padL = 56, padR = 130, padT = 16, padB = 44;
  const max = opts.max || Math.max(10, ...series.flatMap((s) => s.points)) * 1.25;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": opts.alt || "Line chart of the reproduced values" });
  const X = (i) => padL + ((W - padL - padR) * i) / Math.max(1, xs.length - 1);
  const Y = (v) => H - padB - ((H - padT - padB) * v) / max;
  for (let t = 0; t <= max; t += max > 50 ? 25 : 10) {
    svg.appendChild(svgEl("line", { x1: padL, y1: Y(t), x2: W - padR, y2: Y(t),
      stroke: "currentColor", "stroke-opacity": 0.14 }));
    const lab = svgEl("text", { x: padL - 8, y: Y(t) + 4, "text-anchor": "end", "font-size": 11, "fill-opacity": 0.6 });
    lab.textContent = Math.round(t) + "%";
    svg.appendChild(lab);
  }
  xs.forEach((x, i) => {
    const lab = svgEl("text", { x: X(i), y: H - padB + 20, "text-anchor": "middle", "font-size": 12 });
    lab.textContent = "k = " + x;
    svg.appendChild(lab);
  });
  series.forEach((s, si) => {
    const colors = ["#2f6690", "#b0453a", "#d9a441", "#2e6b4f", "#7a5ea8"];
    const col = s.color || colors[si % colors.length];
    svg.appendChild(svgEl("polyline", { points: s.points.map((v, i) => `${X(i)},${Y(v)}`).join(" "),
      fill: "none", stroke: col, "stroke-width": 2.2 }));
    s.points.forEach((v, i) => svg.appendChild(svgEl("circle", { cx: X(i), cy: Y(v), r: 4, fill: col })));
    const lab = svgEl("text", { x: W - padR + 10, y: Y(s.points[s.points.length - 1]) + 4,
      "font-size": 12, fill: col, "font-weight": 600 });
    lab.textContent = s.label;
    svg.appendChild(lab);
  });
  return svg;
}

/* ---------------------------------------------------------------- result cards */

function table(headers, rows) {
  const t = el("table");
  const thead = el("thead");
  thead.appendChild(el("tr", {}, headers.map((h) => el("th", { text: h }))));
  t.appendChild(thead);
  const tb = el("tbody");
  for (const r of rows) {
    tb.appendChild(el("tr", {}, r.map((c, i) =>
      el("td", { class: i === 0 ? "" : "num", text: String(c) }))));
  }
  t.appendChild(tb);
  return t;
}

function card(title, settingsLine) {
  const c = el("div", { class: "card" });
  c.appendChild(el("h3", { text: "Reproduced result" }));
  c.appendChild(el("p", { class: "sub", text: title }));
  if (settingsLine) c.appendChild(el("p", { class: "sub", text: "Settings: " + settingsLine }));
  return c;
}

function details(summaryText, lines) {
  const d = el("details");
  d.appendChild(el("summary", { text: summaryText }));
  d.appendChild(el("pre", { text: lines.join("\n") }));
  return d;
}

/* ---------------------------------------------------------------- the five analyses */

function runDiscovery() {
  const E = DATA.experiments.discovery_vs_localized;
  const v = $("stratum").value;
  let blk, label;
  if (v === "pooled") { blk = E.pooled; label = "all systems pooled"; }
  else {
    const [kind, key] = v.split(":");
    blk = { model: E.by_model, family: E.by_family, domain: E.by_domain }[kind][key];
    label = { model: (DATA.models.find((m) => m.id === key) || {}).label,
              family: key.replace(/_/g, " ") + " relations",
              domain: E.domain_labels[key] || key }[kind];
  }
  const tRate = pct(blk.targeted.x, blk.targeted.n), bRate = pct(blk.blind.x, blk.blind.n);
  const diff = tRate - bRate;
  const p = exactMcNemar(blk.b, blk.c);
  const [lo, hi] = pairedCI(blk.both, blk.b, blk.c, blk.neither);

  const c = card("Discovery vs relation-localized verification", label);
  c.appendChild(el("p", { class: "headline " + (diff >= 0 ? "pos" : "neg"), text: fmtPP(diff) }));
  c.appendChild(el("p", { class: "sub",
    text: `relation-localized minus blind discovery · 95% CI [${lo.toFixed(1)}, ${hi.toFixed(1)}] pp · exact McNemar ${fmtP(p)}` }));
  c.appendChild(table(["Condition", "Correct", "Cases", "Rate"], [
    ["Relation-localized", blk.targeted.x, blk.targeted.n, fmtPct(tRate)],
    ["Blind discovery", blk.blind.x, blk.blind.n, fmtPct(bRate)],
  ]));
  c.appendChild(table(["Paired cell", "Count", "", ""], [
    ["Both correct", blk.both, "", ""],
    ["Localized only (b)", blk.b, "", ""],
    ["Blind only (c)", blk.c, "", ""],
    ["Neither", blk.neither, "", ""],
  ]));
  c.appendChild(barChart([
    { label: "Blind discovery", value: bRate, color: "#b0453a" },
    { label: "Relation-localized", value: tRate, color: "#2f6690" },
  ], { alt: `Blind discovery ${fmtPct(bRate)} against relation-localized ${fmtPct(tRate)}` }));
  c.appendChild(details("How was this calculated?", [
    "Inputs (from docs/data/public_sufficient_statistics.json):",
    `  targeted = ${blk.targeted.x}/${blk.targeted.n}`,
    `  blind    = ${blk.blind.x}/${blk.blind.n}`,
    `  paired 2x2: both=${blk.both}  b=${blk.b}  c=${blk.c}  neither=${blk.neither}`,
    "",
    "Rates:",
    `  localized = 100 * ${blk.targeted.x} / ${blk.targeted.n} = ${tRate.toFixed(3)}%`,
    `  blind     = 100 * ${blk.blind.x} / ${blk.blind.n} = ${bRate.toFixed(3)}%`,
    `  difference = ${diff.toFixed(3)} pp`,
    "",
    "Exact two-sided McNemar on the discordant pairs only:",
    `  n = b + c = ${blk.b} + ${blk.c} = ${blk.b + blk.c},  k = min(b, c) = ${Math.min(blk.b, blk.c)}`,
    "  p = min(1, 2 * sum_{i<=k} C(n,i) / 2^n)   [exact integer arithmetic, BigInt]",
    `  p = ${p}`,
    "",
    "95% interval: Newcombe method 10 (square-and-add on Wilson intervals for the two",
    "marginal proportions, with the phi correlation from the 2x2 table).",
  ]));
  return c;
}

function runRanking() {
  const E = DATA.experiments.ranking;
  const m = $("rmodel").value;
  const k = document.querySelector('input[name="k"]:checked').value;
  const at = E.by_model[m][k], at1 = E.by_model[m]["1"];
  const rate = pct(at.x, at.n), base = pct(at1.x, at1.n);
  const label = (DATA.models.find((x) => x.id === m) || {}).label;

  const c = card("Recall@k from the blind ranked finding list", `${label}, k = ${k}`);
  c.appendChild(el("p", { class: "headline", text: fmtPct(rate) }));
  c.appendChild(el("p", { class: "sub",
    text: `Recall@${k} = ${at.x}/${at.n}  ·  gain over Recall@1: ${fmtPP(rate - base)}` }));
  const ks = E.ks_observable.map(String);
  c.appendChild(table(["k", "Found", "Cases", "Recall@k"],
    ks.map((kk) => [kk, E.by_model[m][kk].x, E.by_model[m][kk].n, fmtPct(pct(E.by_model[m][kk].x, E.by_model[m][kk].n))])));
  c.appendChild(lineChart(
    [{ label: label, points: ks.map((kk) => pct(E.by_model[m][kk].x, E.by_model[m][kk].n)) }],
    ks, { max: 100, alt: `Recall at k for ${label}` }));
  c.appendChild(el("p", { class: "hint", text: E.budget_note }));
  c.appendChild(details("How was this calculated?", [
    `Recall@${k} = (blind audits whose correct finding appeared at rank <= ${k}) / (cases scored)`,
    `            = ${at.x} / ${at.n} = ${rate.toFixed(3)}%`,
    "",
    `Recall@1 = ${at1.x} / ${at1.n} = ${base.toFixed(3)}%`,
    `Gain from k=1 to k=${k}: ${(rate - base).toFixed(3)} pp`,
    "",
    "Only k in {1, 2, 3, 5} is observable: the blind response schema caps a system at five",
    "findings, and k = 4 was not stored as a separate cell. Nothing is claimed about ranks",
    "beyond five, and Recall@10 is not recoverable from the frozen records.",
  ]));
  return c;
}

function runAgentic() {
  const E = DATA.experiments.agentic;
  const mode = document.querySelector('input[name="conds"]:checked').value;
  const d = pct(E.direct_blind.x, E.direct_blind.n);
  const a = pct(E.agentic_blind.x, E.agentic_blind.n);
  const l = pct(E.relation_localized.x, E.relation_localized.n);
  const label = (DATA.models.find((m) => m.id === E.model) || {}).label;

  const rows = [["Direct blind", E.direct_blind.x, E.direct_blind.n, fmtPct(d)]];
  const bars = [{ label: "Direct blind", value: d, color: "#b0453a" }];
  if (mode !== "agentic_vs_localized" || mode === "all_three") {
    rows.push(["Bounded agentic blind", E.agentic_blind.x, E.agentic_blind.n, fmtPct(a)]);
    bars.push({ label: "Bounded agentic", value: a, color: "#d9a441" });
  }
  if (mode !== "direct_vs_agentic") {
    rows.push(["Relation-localized", E.relation_localized.x, E.relation_localized.n, fmtPct(l)]);
    bars.push({ label: "Relation-localized", value: l, color: "#2f6690" });
  }
  if (mode === "agentic_vs_localized") {
    rows.splice(0, 1); bars.splice(0, 1);
    rows.unshift(["Bounded agentic blind", E.agentic_blind.x, E.agentic_blind.n, fmtPct(a)]);
    bars.unshift({ label: "Bounded agentic", value: a, color: "#d9a441" });
  }

  const pr = E.paired_agentic_vs_direct;
  const p = exactMcNemar(pr.b, pr.c);
  const [lo, hi] = pairedCI(pr.both, pr.b, pr.c, pr.neither);
  const deficit = l - d;
  const recovered = deficit > 0 ? (100 * (a - d)) / deficit : NaN;

  const c = card("Bounded agentic navigation", `${label} · ${mode.replace(/_/g, " ")}`);
  c.appendChild(el("p", { class: "headline pos", text: fmtPP(a - d) }));
  c.appendChild(el("p", { class: "sub",
    text: `bounded agentic minus direct blind · 95% CI [${lo.toFixed(1)}, ${hi.toFixed(1)}] pp · exact McNemar ${fmtP(p)}` }));
  c.appendChild(table(["Condition", "Correct", "Cases", "Rate"], rows));
  c.appendChild(table(["Quantity", "Value", "", ""], [
    ["Direct-to-localized deficit", deficit.toFixed(1) + " pp", "", ""],
    ["Of that, recovered", Math.round(recovered) + "%", "", ""],
    ["False-positive findings per case, direct", E.false_positive_findings_per_case.direct, "", ""],
    ["False-positive findings per case, agentic", E.false_positive_findings_per_case.agentic, "", ""],
    ["Tool-call budget", E.tool_calls.budget, "", ""],
    ["Mean tool calls used", E.tool_calls.mean, "", ""],
  ]));
  c.appendChild(barChart(bars, { alt: "Detection rates by condition" }));
  c.appendChild(el("div", { class: "note", text:
    "Bounded agentic navigation recovered part of the observed direct-to-localized deficit. " +
    "The sensitivity gain came with more than twice as many false-positive findings per case, and the " +
    "budget was nearly saturated, so this is a lower bound on what unbounded navigation might reach. " +
    "The unrecovered portion is not characterized as non-search-limited." }));
  c.appendChild(details("How was this calculated?", [
    `direct blind       = ${E.direct_blind.x}/${E.direct_blind.n} = ${d.toFixed(3)}%`,
    `bounded agentic    = ${E.agentic_blind.x}/${E.agentic_blind.n} = ${a.toFixed(3)}%`,
    `relation-localized = ${E.relation_localized.x}/${E.relation_localized.n} = ${l.toFixed(3)}%`,
    "",
    `deficit   = localized - direct = ${l.toFixed(3)} - ${d.toFixed(3)} = ${deficit.toFixed(3)} pp`,
    `recovered = (agentic - direct) / deficit = (${a.toFixed(3)} - ${d.toFixed(3)}) / ${deficit.toFixed(3)}`,
    `          = ${(recovered / 100).toFixed(4)} = ${Math.round(recovered)}%`,
    "",
    `paired 2x2 (agentic vs direct): both=${pr.both} b=${pr.b} c=${pr.c} neither=${pr.neither}`,
    `exact two-sided McNemar on b and c: ${p}`,
  ]));
  return c;
}

function runTransfer() {
  const E = DATA.experiments.information_transfer;
  const A = $("armA").value, B = $("armB").value;
  if (A === B) {
    const c = card("Information transfer between verifiers", "pick two different conditions");
    c.appendChild(el("p", { class: "sub", text: "Condition A and condition B are the same arm. Choose two different conditions." }));
    return c;
  }
  const ra = pct(E.arms[A].x, E.arms[A].n), rb = pct(E.arms[B].x, E.arms[B].n);
  const la = E.arm_labels[A] || A, lb = E.arm_labels[B] || B;
  const diff = ra - rb;

  let frozen = null;
  for (const [, ct] of Object.entries(E.frozen_contrasts)) {
    if ((ct.a_arm === A && ct.b_arm === B) || (ct.a_arm === B && ct.b_arm === A)) { frozen = ct; break; }
  }

  const c = card("Information transfer between verifiers", `${la} vs ${lb}`);
  c.appendChild(el("p", { class: "headline " + (diff >= 0 ? "pos" : "neg"), text: fmtPP(diff) }));
  c.appendChild(el("p", { class: "sub", text: `unpaired difference in downstream accuracy, A minus B` }));
  c.appendChild(table(["Upstream condition", "Correct", "Trials", "Downstream accuracy"], [
    ["A — " + la, E.arms[A].x, E.arms[A].n, fmtPct(ra)],
    ["B — " + lb, E.arms[B].x, E.arms[B].n, fmtPct(rb)],
  ]));

  const calc = [
    `rate A = ${E.arms[A].x} / ${E.arms[A].n} = ${ra.toFixed(3)}%`,
    `rate B = ${E.arms[B].x} / ${E.arms[B].n} = ${rb.toFixed(3)}%`,
    `unpaired difference = ${diff.toFixed(3)} pp`,
  ];
  if (frozen) {
    const flip = frozen.a_arm !== A;
    const b = flip ? frozen.c : frozen.b, cc = flip ? frozen.b : frozen.c;
    const p = exactMcNemar(b, cc);
    const [lo, hi] = pairedCI(frozen.both, b, cc, frozen.neither);
    const pd = (100 * (b - cc)) / frozen.n;
    c.appendChild(el("p", { class: "sub",
      text: `Paired on the same cases: ${fmtPP(pd)} · 95% CI [${lo.toFixed(1)}, ${hi.toFixed(1)}] pp · exact McNemar ${fmtP(p)}` }));
    c.appendChild(table(["Paired cell", "Count", "", ""], [
      ["Both correct", frozen.both, "", ""], ["A only (b)", b, "", ""],
      ["B only (c)", cc, "", ""], ["Neither", frozen.neither, "", ""],
    ]));
    calc.push("", "This pair matches a frozen paired contrast:", `  "${frozen.question}"`,
      `  paired 2x2: both=${frozen.both} b=${b} c=${cc} neither=${frozen.neither}`,
      `  paired difference = 100 * (b - c) / n = 100 * (${b} - ${cc}) / ${frozen.n} = ${pd.toFixed(3)} pp`,
      `  exact two-sided McNemar from b and c = ${p}`,
      `  frozen exact p from the analysis artifact = ${frozen.frozen_exact_p}`,
      `  frozen 95% CI = [${frozen.frozen_ci95_pp[0]}, ${frozen.frozen_ci95_pp[1]}] pp`);
    if (lo <= 0 && hi >= 0) {
      c.appendChild(el("div", { class: "note", text: E.null_note }));
    }
  } else {
    c.appendChild(el("p", { class: "hint", text:
      "This pair was not run as a frozen paired contrast, so only the unpaired arm rates are shown. An unpaired difference is not a paired test." }));
  }

  const order = Object.keys(E.arms).sort((x, y) => pct(E.arms[y].x, E.arms[y].n) - pct(E.arms[x].x, E.arms[x].n));
  c.appendChild(barChart(order.map((k) => ({
    label: E.arm_labels[k] || k, value: pct(E.arms[k].x, E.arms[k].n),
    color: k === A ? "#2f6690" : k === B ? "#b0453a" : "#b8b8b8",
  })), { max: 100, alt: "Downstream accuracy for every upstream arm" }));
  c.appendChild(details("How was this calculated?", calc));
  return c;
}

function runProfile() {
  const E = DATA.experiments.evidence_profile;
  const m = $("pmodel").value, d = E.by_model[m];
  const label = (DATA.models.find((x) => x.id === m) || {}).label;
  const v = d.verdict_x_provenance;
  const correct = v.CORRECT_RELATION_SUPPORTED + v.CORRECT_UNSUPPORTED;
  const provShare = pct(v.CORRECT_RELATION_SUPPORTED, correct);
  const disc = pct(d.discovery_recall_at_1.x, d.discovery_recall_at_1.n);
  const loc = pct(d.relation_localized.x, d.relation_localized.n);
  const traj = pct(d.trajectory.x, d.trajectory.n);
  const fa = pct(d.false_alarm.x, d.false_alarm.n);
  const totalVP = Object.values(v).reduce((s, x) => s + x, 0);

  const c = card("Verification Evidence Profile", label);
  c.appendChild(el("p", { class: "sub", text:
    "Four components, reported side by side. There is deliberately no single score." }));
  c.appendChild(table(["Component", "Count", "Denominator", "Value"], [
    ["Discovery (Recall@1, blind)", d.discovery_recall_at_1.x, d.discovery_recall_at_1.n, fmtPct(disc)],
    ["Relation-localized accuracy", d.relation_localized.x, d.relation_localized.n, fmtPct(loc)],
    ["Evidence responsiveness (all of E0/E1/E2)", d.trajectory.x, d.trajectory.n, fmtPct(traj)],
    ["Provenance (relation-supporting | correct)", v.CORRECT_RELATION_SUPPORTED, correct, fmtPct(provShare)],
    ["Specificity (false-alarm rate)", d.false_alarm.x, d.false_alarm.n, fmtPct(fa)],
  ]));
  c.appendChild(barChart([
    { label: "Discovery (Recall@1)", value: disc, color: "#b0453a" },
    { label: "Relation-localized", value: loc, color: "#2f6690" },
    { label: "Full E0/E1/E2 trajectory", value: traj, color: "#7a5ea8" },
    { label: "Provenance | correct", value: provShare, color: "#2e6b4f" },
    { label: "False-alarm rate", value: fa, color: "#d9a441" },
  ], { max: 100, alt: `Verification Evidence Profile for ${label}` }));
  c.appendChild(el("h3", { text: "Verdict × provenance" }));
  c.appendChild(table(["Cell", "Trials", "Share", ""], Object.entries(v).map(([k, n]) =>
    [k.replace(/_/g, " ").toLowerCase(), n, fmtPct(pct(n, totalVP)), ""])));
  c.appendChild(el("p", { class: "hint", text:
    "The incorrect-but-relation-supported cell is the adjudication failure: the system reached the right lines and still ruled wrongly." }));
  c.appendChild(details("How was this calculated?", [
    `discovery        = ${d.discovery_recall_at_1.x} / ${d.discovery_recall_at_1.n} = ${disc.toFixed(3)}%  (Recall@1, blind)`,
    `localized        = ${d.relation_localized.x} / ${d.relation_localized.n} = ${loc.toFixed(3)}%`,
    `trajectory       = ${d.trajectory.x} / ${d.trajectory.n} = ${traj.toFixed(3)}%  (${E.definitions.trajectory})`,
    `provenance|corr  = ${v.CORRECT_RELATION_SUPPORTED} / (${v.CORRECT_RELATION_SUPPORTED} + ${v.CORRECT_UNSUPPORTED}) = ${provShare.toFixed(3)}%`,
    `false alarm      = ${d.false_alarm.x} / ${d.false_alarm.n} = ${fa.toFixed(3)}%  (${E.definitions.false_alarm})`,
    "",
    "verdict x provenance cells:",
    ...Object.entries(v).map(([k, n]) => `  ${k.padEnd(28)} ${n}`),
  ]));
  return c;
}

const RUNNERS = { discovery: runDiscovery, ranking: runRanking, agentic: runAgentic,
                  transfer: runTransfer, profile: runProfile };

/* ---------------------------------------------------------------- wiring */

function reset() {
  $("output").textContent = "";          // the chart and every number leave the DOM
  $("reset").disabled = true;
  $("status").textContent = "";
}

async function init() {
  const expSel = $("experiment");
  const setHint = () => { $("experiment-hint").textContent = HINTS[expSel.value] || ""; };

  try {
    const res = await fetch("data/public_sufficient_statistics.json", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    DATA = await res.json();
  } catch (e) {
    $("settings").appendChild(el("p", { class: "hint",
      text: "Could not load the aggregate statistics file (" + e.message + "). " +
            "If you opened this page from the filesystem, serve it over HTTP instead: python -m http.server." }));
    $("run").disabled = true;
    return;
  }

  buildSettings(expSel.value);
  setHint();
  expSel.addEventListener("change", () => { buildSettings(expSel.value); setHint(); reset(); });

  $("controls").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const out = $("output");
    out.textContent = "";
    let node;
    try {
      node = RUNNERS[expSel.value]();
    } catch (e) {
      node = el("div", { class: "card" }, [
        el("h3", { text: "Could not reproduce" }),
        el("p", { class: "sub", text: String(e && e.message ? e.message : e) }),
      ]);
    }
    out.appendChild(node);
    $("reset").disabled = false;
    $("status").textContent = "Result computed in your browser.";
    node.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  $("reset").addEventListener("click", reset);
}

document.addEventListener("DOMContentLoaded", init);
