/* Minimal DOM shim, enough to execute docs/assets/app.js in a JS engine without a browser.
   Used by tests/test_playground.py. Not shipped to the site. */
globalThis.__log = [];
const REG = {};   // id -> node, populated whenever an id attribute is set

class Node {
  constructor(tag, ns) {
    this.tagName = String(tag).toUpperCase(); this.nodeName = this.tagName; this.ns = ns || null;
    this.children = []; this.attributes = {}; this._text = ""; this.listeners = {};
    this.className = ""; this.disabled = false; this.checked = false; this.value = "";
    this.parentNode = null;
  }
  appendChild(c) {
    c.parentNode = this; this.children.push(c);
    // a real <select> selects its first <option> by default
    if (this.tagName === "SELECT" && c.tagName === "OPTION" && this.value === "") this.value = c.value;
    return c;
  }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === "value") this.value = String(v);
    if (k === "id") { this.id = String(v); REG[this.id] = this; }
    if (k === "name") this.name = String(v);
    if (k === "type") this.type = String(v);
  }
  getAttribute(k) { return this.attributes[k] ?? null; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  dispatch(t, ev) { for (const fn of this.listeners[t] || []) fn(ev || { preventDefault() {} }); }
  scrollIntoView() {}
  focus() {}
  set textContent(v) {
    this._text = String(v);
    if (v === "") this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join("");
  }
  /* test helpers */
  all(pred, acc) { acc = acc || []; if (pred(this)) acc.push(this);
                   for (const c of this.children) c.all(pred, acc); return acc; }
  byTag(t) { return this.all((n) => n.tagName === t.toUpperCase()); }
  html() {
    if (this.tagName === "#TEXT") return this._text;
    const a = Object.entries(this.attributes).map(([k, v]) => ` ${k}="${v}"`).join("");
    return `<${this.tagName.toLowerCase()}${a}>${this._text}` +
           this.children.map((c) => c.html()).join("") + `</${this.tagName.toLowerCase()}>`;
  }
}

globalThis.document = {
  _nodes: REG,
  createElement(t) { return new Node(t); },
  createTextNode(t) { const n = new Node("#text"); n.textContent = String(t); return n; },
  createElementNS(ns, t) { return new Node(t, ns); },
  getElementById(id) { return REG[id] || null; },
  register(id, node) { node.id = id; REG[id] = node; return node; },
  querySelector(sel) {
    const m = /^input\[name="([^"]+)"\]:checked$/.exec(sel);
    if (m) {
      for (const n of Object.values(REG)) {
        const hit = n.all((x) => x.tagName === "INPUT" && x.name === m[1] && x.checked);
        if (hit.length) return hit[0];
      }
      return null;
    }
    throw new Error("shim: unsupported selector " + sel);
  },
  addEventListener(t, fn) { (this._l = this._l || {})[t] = fn; },
  fire(t) { if (this._l && this._l[t]) this._l[t](); },
};

/* the page's static scaffolding, mirroring docs/index.html */
for (const id of ["experiment", "experiment-hint", "settings", "run", "reset", "status", "output", "controls"]) {
  document.register(id, new Node(id === "experiment" ? "select" : id === "controls" ? "form" : "div"));
}
globalThis.setTimeout = (fn) => { fn(); return 0; };

globalThis.fetch = async (url) => ({
  ok: true, status: 200,
  json: async () => JSON.parse(globalThis.__STATS_JSON),
});
