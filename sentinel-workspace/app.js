/* ClearGlass Sentinel Workspace · application layer.
   ────────────────────────────────────────────────────────────────────────────
   DOM, interaction and persistence only. Every analytical rule lives in
   core.js (window.SentinelCore) so it can be tested without a browser.

   Safety rules applied throughout this file:
   - All dataset and analyst text is inserted with textContent / text nodes.
     Nothing from data is ever assigned to innerHTML.
   - The only link built from data is a source URI that core.js has already
     restricted to http(s); it opens with rel="noopener noreferrer".
   - No network request leaves this origin (see the page's CSP).
   - Browser storage holds the notebook and view state only; imported
     datasets stay in memory. Storage is editable and not tamper-evident. */
(function () {
  "use strict";
  var C = window.SentinelCore;
  if (!C) {
    var st = document.getElementById("canvasState");
    if (st) { st.textContent = "The analysis module (core.js) did not load. Reload the page."; }
    return;
  }

  /* ───────────────────────── constants ───────────────────────── */
  var SVGNS = "http://www.w3.org/2000/svg";
  var PREFIX = "cg.sentinel.ws.v1.";
  var BUNDLED = {
    id: "ds-lookalike-domain-exercise",
    v1: "sentinel-workspace/fixtures/lookalike-domain-v1.json",
    v2: "sentinel-workspace/fixtures/lookalike-domain-v2.json"
  };
  var DEFAULT_REVIEW = ["unreviewed", "confirmed", "disputed"];
  var GLYPH = { person: "PER", organization: "ORG", domain: "DOM", ip: "IP", system: "SYS", document: "DOC", account: "ACC", certificate: "CRT", topic: "TOP", other: "OTH" };
  var TYPE_NAME = { person: "Person", organization: "Organization", domain: "Domain", ip: "IP address", system: "System", document: "Document", account: "Account", certificate: "Certificate", topic: "Topic", other: "Other" };
  var NODE_R = 15;
  var KIND_LABEL = { entity: "Entity", relationship: "Relationship", claim: "Claim", observation: "Evidence record", source: "Source", finding: "Finding", merge: "Merge candidate" };
  var LAYER_OF_CLAIM = { observed: ["observed", "OBSERVED"], derived: ["derived", "DERIVED"], hypothesized: ["hypothesized", "HYPOTHESIZED"], "analyst-assessed": ["analyst", "ANALYST-ASSESSED"] };

  /* ───────────────────────── state ───────────────────────── */
  var S = {
    ds: null, idx: null, fp: null, origin: null, warnings: [],
    nb: null, resolver: C.mergeResolver([]),
    view: {
      layout: "radial", seed: 1337, focus: null, hops: 0, rep: "graph", tableTab: "entities",
      filters: { entityTypes: null, relTypes: null, review: DEFAULT_REVIEW.slice(), window: null },
      pinned: new Map()
    },
    graph: null, graphMetrics: null, positions: new Map(), layoutMeta: null, layoutHistory: [],
    selection: null, history: [],
    zoom: { x: 0, y: 0, k: 1 }, fitK: 1,
    findings: new Map(), runSeq: 0, metricsRunId: null, pathRunId: null, activePath: null,
    compare: null, events: [], jobToken: 0, storageOk: true, mode: "explore",
    nodeEls: new Map(), edgeEls: new Map(), rovingId: null, sort: { key: "label", dir: 1 }
  };

  /* ───────────────────────── tiny DOM helpers ───────────────────────── */
  function $(id) { return document.getElementById(id); }
  function setAttrs(el, attrs) {
    if (!attrs) return;
    Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "text") el.textContent = v;
      else if (k.slice(0, 2) === "on" && typeof v === "function") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : String(v));
    });
  }
  function add(el, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { add(el, x); }); return; }
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  function h(tag, attrs) {
    var el = document.createElement(tag);
    setAttrs(el, attrs);
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function sv(tag, attrs) {
    var el = document.createElementNS(SVGNS, tag);
    setAttrs(el, attrs);
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function btn(label, onclick, cls, attrs) { return h("button", Object.assign({ type: "button", class: "btn " + (cls || "sm"), onclick: onclick }, attrs || {}), label); }
  function isMobile() { return window.matchMedia("(max-width: 860px)").matches; }
  function reducedMotion() { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
  function nowIso() { return new Date().toISOString(); }

  function fmtTime(v) {
    if (v === null || v === undefined) return "unknown";
    if (!/T/.test(v)) return v + " (date only)";
    var t = Date.parse(v);
    return isNaN(t) ? String(v) : new Date(t).toISOString().replace("T", " ").slice(0, 16) + " UTC";
  }
  function dayDiff(a, b) { return Math.round((Date.parse(b) - Date.parse(a)) / 86400000); }
  function shortFp(fp) { return C.shortFingerprint(fp); }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
  function truncate(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  function stamp() { return nowIso().replace(/[:.]/g, "-").slice(0, 19); }

  var toastTimer = 0;
  function toast(msg) {
    var t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove("show"); }, 2600);
  }

  /* Session activity: UI history only. Messages carry counts and identifiers,
     never excerpt text or attribute values. */
  function log(kind, text) {
    S.events.unshift({ t: new Date(), kind: kind, text: text });
    if (S.events.length > 300) S.events.length = 300;
    $("activityCount").textContent = String(S.events.length);
    $("activityLast").textContent = text;
    if (!$("activityPanel").hidden) renderActivity();
  }
  function renderActivity() {
    var ol = clear($("activityList"));
    S.events.forEach(function (e) {
      ol.appendChild(h("li", null, h("span", { class: "t" }, e.t.toISOString().slice(11, 19)), h("span", { class: "tag" }, e.kind), " ", e.text));
    });
  }

  /* ───────────────────────── storage ───────────────────────── */
  function storeGet(key) {
    try { var v = localStorage.getItem(PREFIX + key); return v === null ? null : JSON.parse(v); } catch (e) { S.storageOk = false; return null; }
  }
  function storeSet(key, value) {
    try { localStorage.setItem(PREFIX + key, JSON.stringify(value)); S.storageOk = true; }
    catch (e) { S.storageOk = false; }
    renderStorageState();
  }
  function storeKeys() {
    var out = [];
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k && k.indexOf(PREFIX) === 0) out.push({ key: k, bytes: (localStorage.getItem(k) || "").length * 2 });
      }
    } catch (e) { S.storageOk = false; }
    return out;
  }
  function storeClearAll() {
    storeKeys().forEach(function (k) { try { localStorage.removeItem(k.key); } catch (e) { /* ignore */ } });
  }
  function renderStorageState() {
    $("storageState").textContent = S.storageOk ? "notebook saved in this browser" : "storage unavailable — notebook kept in memory only";
  }
  function saveNotebook() { if (S.ds && S.nb) storeSet("nb." + S.ds.dataset.id, S.nb); }
  function saveView() {
    if (!S.ds) return;
    storeSet("view." + S.ds.dataset.id, viewState());
  }
  function viewState() {
    var pinned = [];
    S.view.pinned.forEach(function (p, id) { pinned.push({ id: id, x: Math.round(p.x * 10) / 10, y: Math.round(p.y * 10) / 10 }); });
    var f = S.view.filters;
    return {
      schema: C.VIEW_SCHEMA, dataset_id: S.ds ? S.ds.dataset.id : null, dataset_fingerprint: S.fp,
      layout: S.view.layout, seed: S.view.seed, focus: S.view.focus, hops: S.view.hops,
      entityTypes: f.entityTypes, relTypes: f.relTypes, review: f.review, window: f.window,
      pinned: pinned, selection: S.selection, saved_at: nowIso()
    };
  }
  function applyViewState(v, opts) {
    var check = C.validateView(v, S.idx);
    if (!check.ok) { showErrors("View state not applied", check.errors, "The file does not match the view-state format."); return false; }
    if (v.layout) S.view.layout = v.layout;
    if (typeof v.seed === "number" && isFinite(v.seed)) S.view.seed = v.seed >>> 0;
    S.view.focus = v.focus && S.idx.entity.has(v.focus) ? v.focus : null;
    S.view.hops = S.view.focus ? (v.hops || 0) : 0;
    var f = S.view.filters;
    f.entityTypes = v.entityTypes === undefined ? null : v.entityTypes;
    f.relTypes = v.relTypes === undefined ? null : v.relTypes;
    f.review = v.review === undefined ? DEFAULT_REVIEW.slice() : v.review;
    f.window = v.window && typeof v.window === "object" ? { from: v.window.from || null, to: v.window.to || null, includeUnknown: !!v.window.includeUnknown } : null;
    S.view.pinned = new Map();
    (v.pinned || []).forEach(function (p) {
      if (p && typeof p.id === "string" && isFinite(p.x) && isFinite(p.y) && S.idx.entity.has(p.id)) S.view.pinned.set(p.id, { x: +p.x, y: +p.y });
    });
    if (v.selection && typeof v.selection === "object" && typeof v.selection.id === "string" && C.kindOf(S.idx, v.selection.id)) {
      S.selection = { kind: v.selection.kind === "relationship" ? "relationship" : (C.kindOf(S.idx, v.selection.id) === "entity" ? "entity" : C.kindOf(S.idx, v.selection.id)), id: v.selection.id };
    }
    if (!opts || !opts.silent) { log("view", "View state applied"); toast("View state applied"); }
    return true;
  }

  /* ───────────────────────── data loading ───────────────────────── */
  function setCanvasState(kind, title, body, actions) {
    var st = $("canvasState");
    if (!kind) { st.hidden = true; return; }
    st.hidden = false;
    clear(st);
    var box = h("div", { class: "box" });
    if (kind === "loading") box.appendChild(h("span", { class: "spin", "aria-hidden": "true" }));
    box.appendChild(h("h3", null, title));
    if (body) box.appendChild(h("p", { class: "note" }, body));
    if (actions) box.appendChild(h("div", { class: "row" }, actions));
    st.appendChild(box);
  }

  function fetchText(url) {
    return fetch(url, { credentials: "same-origin", cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.text();
    });
  }

  function loadBundled(which) {
    setCanvasState("loading", "Loading the bundled training dataset…");
    return fetchText(which === "v2" ? BUNDLED.v2 : BUNDLED.v1).then(function (text) {
      var r = C.parseDataset(text);
      if (!r.ok) { showErrors("Bundled dataset failed validation", r.errors); throw new Error("invalid bundled dataset"); }
      install(r, { kind: "bundled", name: which === "v2" ? "lookalike-domain-v2.json" : "lookalike-domain-v1.json", bytes: r.bytes });
    }).catch(function (err) {
      var offline = typeof navigator !== "undefined" && navigator.onLine === false;
      var fileProto = location.protocol === "file:";
      setCanvasState("error", offline ? "You appear to be offline" : "The bundled dataset could not be loaded",
        fileProto ? "This page was opened from a file, and browsers block reading other local files from it. Serve the folder over HTTP, or import a dataset file instead."
          : (offline ? "Reconnect to load the bundled dataset, or import a dataset file from this device." : "Reason: " + String(err && err.message || err) + ". You can retry or import a dataset file."),
        [btn("Retry", function () { loadBundled(which); }, "primary"), btn("Import a dataset file…", function () { $("fileDataset").click(); })]);
      log("error", "Bundled dataset not loaded (" + String(err && err.message || err) + ")");
    });
  }

  function readFileChecked(file, cb) {
    if (!file) return;
    if (file.size > C.LIMITS.maxBytes) {
      showErrors("File not loaded", [{ path: "$", message: "File is " + file.size + " bytes; the limit is " + C.LIMITS.maxBytes + " bytes. It was not read." }]);
      log("error", "Import refused: file over size limit (" + file.size + " bytes)");
      return;
    }
    file.text().then(cb, function () { showErrors("File not loaded", [{ path: "$", message: "The browser could not read the file." }]); });
  }

  function importDataset(file) {
    readFileChecked(file, function (text) {
      var r = C.parseDataset(text);
      if (!r.ok) {
        showErrors("Dataset not loaded", r.errors, "Nothing was changed. Fix the listed problems and import again." + (r.truncated ? " Only the first " + C.LIMITS.maxErrors + " problems are shown." : ""));
        log("error", "Import rejected: " + plural(r.errors.length, "validation error"));
        return;
      }
      install(r, { kind: "import", name: file.name, bytes: r.bytes });
      toast("Dataset imported");
    });
  }

  function install(parsed, origin) {
    S.ds = parsed.dataset;
    S.idx = C.buildIndex(S.ds);
    S.fp = parsed.fingerprint;
    S.origin = origin;
    S.warnings = parsed.warnings || [];
    S.selection = null; S.history = []; S.findings = new Map(); S.metricsRunId = null; S.pathRunId = null; S.activePath = null;
    S.layoutHistory = []; S.view.pinned = new Map(); S.view.focus = null; S.view.hops = 0;
    S.view.filters = { entityTypes: null, relTypes: null, review: DEFAULT_REVIEW.slice(), window: null };
    if (S.compare && S.compare.base !== S.fp) S.compare = null;
    var stored = storeGet("nb." + S.ds.dataset.id);
    if (stored && C.validateNotebook(stored).ok) S.nb = stored;
    else {
      if (stored) log("error", "Stored notebook was unreadable and was not used");
      S.nb = C.createNotebook(S.ds, new Date());
      saveNotebook();
    }
    refreshResolver();
    var v = storeGet("view." + S.ds.dataset.id);
    if (v && v.schema === C.VIEW_SCHEMA) applyViewState(v, { silent: true });
    log("data", "Loaded " + (origin.kind === "bundled" ? "bundled" : "imported") + " dataset " + S.ds.dataset.id + " v" + S.ds.dataset.version + " (" + plural(S.ds.entities.length, "entity", "entities") + ", fingerprint " + shortFp(S.fp) + ")");
    setCanvasState(null);
    renderHeader();
    renderBanner();
    recompute({ fit: true });
    renderRail();
    renderInspector();
    renderMode();
  }

  function refreshResolver() {
    S.resolver = C.mergeResolver(C.confirmedMergeGroups(S.nb, S.idx));
  }

  /* ───────────────────────── header, strip, banner ───────────────────────── */
  function renderHeader() {
    var d = S.ds.dataset;
    $("dsSynthetic").hidden = !d.synthetic;
    $("dsTitle").textContent = d.title;
    $("dsMeta").textContent = "v" + d.version + " · as of " + (d.as_of ? d.as_of.slice(0, 10) : "unknown") + " · " + shortFp(S.fp);
    $("dsMeta").title = "Content fingerprint " + S.fp;
  }

  function describeScope() {
    var g = S.graph, f = S.view.filters, parts = [];
    parts.push((g.scope === "full" ? "full dataset" : "visible subgraph") + ": " + (g.nodes.length - g.forced.length) + " of " + g.totals.nodes + " entities, " + g.edges.length + " of " + g.totals.edges + " relationships");
    if (f.entityTypes) parts.push("entity types ∈ {" + f.entityTypes.join(", ") + "}");
    if (f.relTypes) parts.push("relationship types ∈ {" + f.relTypes.join(", ") + "}");
    if (f.review) parts.push("review ∈ {" + f.review.join(", ") + "}");
    if (f.window) parts.push("time window " + (f.window.from || "…") + " to " + (f.window.to || "…") + (f.window.includeUnknown ? " (uncertain timing included)" : " (uncertain timing excluded)"));
    if (S.view.focus && S.view.hops) parts.push("isolated to " + plural(S.view.hops, "hop") + " around " + labelOf(S.view.focus));
    var merged = C.confirmedMergeGroups(S.nb, S.idx).length;
    if (merged) parts.push(plural(merged, "confirmed merge"));
    return parts.join("; ");
  }
  function scopeKey() {
    return JSON.stringify([S.fp, S.view.filters, S.view.focus, S.view.hops, C.confirmedMergeGroups(S.nb, S.idx)]);
  }

  function renderStrip() {
    var el = clear($("strip")), g = S.graph;
    if (!g) return;
    var visibleNodes = g.nodes.length - g.forced.length;
    el.appendChild(h("span", { class: "scope" + (g.scope === "full" ? "" : " sub") }, g.scope === "full" ? "SCOPE · FULL DATASET" : "SCOPE · VISIBLE SUBGRAPH"));
    el.appendChild(h("span", null, h("b", null, visibleNodes), " of " + g.totals.nodes + " entities"));
    el.appendChild(h("span", null, h("b", null, g.edges.length), " of " + g.totals.edges + " relationships"));
    if (g.hidden.nodes || g.hidden.edges) {
      var why = [];
      if (g.excluded.byReview) why.push(g.excluded.byReview + " by review state");
      if (g.excluded.byRelType) why.push(g.excluded.byRelType + " by type");
      if (g.excluded.byEntityType) why.push(g.excluded.byEntityType + " by entity type");
      if (g.excluded.byWindow) why.push(g.excluded.byWindow + " by time window");
      if (g.excluded.byFocus) why.push(g.excluded.byFocus + " outside the neighbourhood");
      el.appendChild(h("span", null, "Hidden: " + plural(g.hidden.nodes, "entity", "entities") + ", " + plural(g.hidden.edges, "relationship") + (why.length ? " (" + why.join(", ") + ")" : "")));
      el.appendChild(btn("Show everything", clearFilters, "sm"));
    }
    if (g.forced.length) el.appendChild(h("span", { class: "tag" }, "selection kept visible"));
    if (S.view.focus && S.view.hops) el.appendChild(h("span", { class: "tag" }, "focus: " + truncate(labelOf(S.view.focus), 28) + " · " + S.view.hops + " hop"));
  }

  function renderBanner() {
    var b = $("banner");
    clear(b);
    b.className = "banner";
    var msgs = [];
    if (S.nb && S.nb.dataset_fingerprint !== S.fp) {
      var known = C.knownIds(S.idx), refs = [];
      S.nb.evidence.forEach(function (e) { refs.push(e.id); });
      S.nb.annotations.forEach(function (a) { refs.push(a.target); });
      var missing = refs.filter(function (r) { return !known.has(r); });
      msgs.push(h("div", { class: "grow" },
        h("b", null, "Notebook from another dataset version. "),
        "This investigation was started on fingerprint " + shortFp(S.nb.dataset_fingerprint) + " (v" + S.nb.dataset_version + "); the loaded data is " + shortFp(S.fp) + " (v" + S.ds.dataset.version + "). " +
        (missing.length ? plural(missing.length, "referenced record") + " no longer exist: " + missing.join(", ") + ". " : "All referenced records still exist. ") +
        "Re-check assessments before relying on them."));
      msgs.push(btn("Adopt this version", function () {
        S.nb = Object.assign({}, S.nb, { dataset_fingerprint: S.fp, dataset_version: S.ds.dataset.version, updated_at: nowIso() });
        S.nb.conclusion_history = (S.nb.conclusion_history || []).concat([{ action: "rebased", at: nowIso(), reason: "Analyst adopted dataset version " + S.ds.dataset.version + " (" + shortFp(S.fp) + ")" }]);
        saveNotebook(); renderBanner(); log("notebook", "Notebook rebased to dataset fingerprint " + shortFp(S.fp));
      }));
    } else if (S.warnings.length) {
      msgs.push(h("div", { class: "grow" }, "Loaded with " + plural(S.warnings.length, "warning") + ": " + S.warnings.slice(0, 3).map(function (w) { return w.path + " — " + w.message; }).join("; ")));
      msgs.push(btn("Dismiss", function () { S.warnings = []; renderBanner(); }));
    }
    b.hidden = !msgs.length;
    add(b, msgs);
  }

  /* ───────────────────────── graph computation ───────────────────────── */
  function labelOf(id) {
    var cid = S.resolver.canonicalOf(id);
    var e = S.idx.entity.get(cid) || S.idx.entity.get(id);
    if (e) return e.label;
    var r = S.idx.relationship.get(id);
    if (r) return labelOf(r.from) + " → " + r.type.replace(/_/g, " ") + " → " + labelOf(r.to);
    var c = S.idx.claim.get(id);
    if (c) return truncate(c.statement, 80);
    var o = S.idx.observation.get(id);
    if (o) return truncate(o.excerpt, 80);
    var s = S.idx.source.get(id);
    if (s) return s.title;
    var f = S.findings.get(id);
    if (f) return f.name;
    var m = S.idx.merge.get(id);
    if (m) return "Merge candidate: " + m.entities.map(labelOf).join(" + ");
    return id;
  }

  function recompute(opts) {
    opts = opts || {};
    var keep = S.selection && S.selection.kind === "entity" ? [S.selection.id] : [];
    S.graph = C.buildGraph(S.ds, S.idx, { resolver: S.resolver, filters: S.view.filters, focus: S.view.focus, hops: S.view.hops, keep: keep });
    S.graphMetrics = null;
    if (S.activePath && !pathStillVisible()) S.activePath = null;
    renderStrip();
    computeLayout(opts);
    if (S.view.rep === "table") renderTables();
    renderTimeline();
    renderRailStatus();
    saveView();
  }
  function pathStillVisible() {
    var ids = new Set(S.graph.edges.map(function (e) { return e.id; }));
    return S.activePath.steps.every(function (s) { return ids.has(s.relationship); });
  }
  function metricsForGraph() {
    if (!S.graphMetrics) S.graphMetrics = C.computeMetrics(S.graph.nodes, S.graph.edges);
    return S.graphMetrics;
  }

  function worldScale(layout, n, extra) {
    if (layout === "radial") return Math.max(250, n * 11, 120 + Math.sqrt(n) * 40);
    if (layout === "hierarchical") return { x: Math.max(260, (extra.maxRow || 1) * 48), y: Math.max(150, (extra.layers || 1) * 62) };
    return Math.max(230, Math.sqrt(n) * 62);
  }
  function scalePositions(pos, sx, sy) {
    var out = new Map();
    pos.forEach(function (p, id) { out.set(id, { x: p.x * sx, y: p.y * (sy === undefined ? sx : sy) }); });
    return out;
  }

  function pushLayoutHistory(reason) {
    var copy = new Map();
    S.positions.forEach(function (p, id) { copy.set(id, { x: p.x, y: p.y }); });
    var pins = new Map();
    S.view.pinned.forEach(function (p, id) { pins.set(id, { x: p.x, y: p.y }); });
    S.layoutHistory.push({ reason: reason, layout: S.view.layout, seed: S.view.seed, positions: copy, pinned: pins, meta: S.layoutMeta });
    if (S.layoutHistory.length > 20) S.layoutHistory.shift();
    $("btnUndoLayout").disabled = false;
  }
  function undoLayout() {
    var last = S.layoutHistory.pop();
    if (!last) return;
    S.view.layout = last.layout; S.view.seed = last.seed; S.view.pinned = last.pinned; S.layoutMeta = last.meta;
    cancelJob();
    S.positions = last.positions;
    ensurePositions();
    renderLayoutSeg(); renderGraph(); fitView(); saveView(); renderRail();
    $("btnUndoLayout").disabled = !S.layoutHistory.length;
    log("layout", "Undid layout change (" + last.reason + ")");
  }

  function computeLayout(opts) {
    var g = S.graph, n = g.nodes.length;
    cancelJob();
    hideLayoutNote();
    if (!n) { S.positions = new Map(); renderGraph(); return; }
    var focus = S.view.focus ? S.resolver.canonicalOf(S.view.focus) : null;
    if (S.view.layout === "hierarchical") {
      var hl = C.layoutHierarchical(g.nodes, g.edges);
      if (hl.ok) {
        var rows = {};
        hl.positions.forEach(function (p) { rows[p.y] = (rows[p.y] || 0) + 1; });
        var maxRow = Math.max.apply(null, Object.keys(rows).map(function (k) { return rows[k]; }));
        var sc = worldScale("hierarchical", n, { maxRow: maxRow, layers: hl.layers });
        applyPositions(scalePositions(hl.positions, sc.x, sc.y), { mode: "hierarchical", layers: hl.layers, unlinkedRow: hl.unlinkedRow, scale: sc }, opts);
        return;
      }
      showLayoutNote("Hierarchy unavailable: " + hl.reason + " Showing the radial layout.");
    }
    if (S.view.layout === "force") { runForceJob(g, opts); return; }
    var r = C.layoutRadial(g.nodes, g.edges, { focus: focus });
    var R = worldScale("radial", n);
    applyPositions(scalePositions(r.positions, R), { mode: r.mode, rings: r.rings, sectors: r.sectors, R: R, focus: r.focus }, opts);
  }

  function applyPositions(pos, meta, opts) {
    S.view.pinned.forEach(function (p, id) { if (pos.has(id)) pos.set(id, { x: p.x, y: p.y }); });
    S.positions = pos;
    S.layoutMeta = meta;
    renderGraph();
    if (opts && opts.fit) fitView(); else if (opts && opts.keepView) { /* keep zoom */ } else fitView();
  }
  function ensurePositions() {
    var missing = S.graph.nodes.filter(function (n) { return !S.positions.has(n.id); });
    if (!missing.length) return;
    var r = C.layoutRadial(S.graph.nodes, S.graph.edges, {});
    var R = worldScale("radial", S.graph.nodes.length);
    missing.forEach(function (n) { var p = r.positions.get(n.id); S.positions.set(n.id, { x: p.x * R, y: p.y * R }); });
  }

  function getWorker() {
    if (S.workerDisabled || typeof Worker === "undefined") return null;
    if (!S.worker) {
      try { S.worker = new Worker("sentinel-workspace/layout-worker.js"); }
      catch (e) { S.workerDisabled = true; return null; }
    }
    return S.worker;
  }
  function showJobSoon(t0, label) {
    $("jobLabel").textContent = label;
    $("jobProgress").value = 0;
    clearTimeout(S.jobShowTimer);
    S.jobShowTimer = setTimeout(function () { if (S.jobToken === t0) $("job").hidden = false; }, 120);
  }
  /* Display-only scaling: choose the world scale so the median
     nearest-neighbour distance is 70 units (enough for a node and a short
     label). Fit then frames the whole graph; local spacing stays readable
     whatever the overall shape. Deterministic for a given layout. */
  function forceScale(pos) {
    var pts = [];
    pos.forEach(function (p) { pts.push(p); });
    if (pts.length < 2) return 230;
    var sample = pts.length > 400 ? pts.filter(function (_p, i) { return i % Math.ceil(pts.length / 400) === 0; }) : pts;
    var nn = sample.map(function (a) {
      var best = Infinity;
      for (var j = 0; j < pts.length; j++) { var b = pts[j]; if (a === b) continue; var d = Math.hypot(a.x - b.x, a.y - b.y); if (d < best) best = d; }
      return best;
    }).sort(function (a, b) { return a - b; });
    var med = nn[Math.floor(nn.length / 2)];
    return med > 1e-9 ? 70 / med : 230;
  }
  function finishForce(token, pos, params, runtime, where, R, n, opts) {
    if (token !== S.jobToken) return;   /* a newer job superseded this one */
    R = forceScale(pos);
    clearTimeout(S.jobShowTimer);
    $("job").hidden = true;
    S.workerBusy = false;
    applyPositions(scalePositions(pos, R), { mode: "force", params: params, runtime_ms: Math.round(runtime), R: R, where: where }, opts);
    log("layout", "Force layout finished: " + n + " entities, " + params.iterations + " iterations, seed " + params.seed + ", " + Math.round(runtime) + " ms (" + where + ")" + (params.approximation ? " (" + params.approximation + ")" : ""));
  }
  function runForceJob(g, opts) {
    var token = ++S.jobToken, n = g.nodes.length;
    var R = S.layoutMeta && S.layoutMeta.mode === "force" && S.layoutMeta.R ? S.layoutMeta.R : worldScale("force", n);
    var pinned = [];
    S.view.pinned.forEach(function (p, id) { pinned.push({ id: id, x: p.x / R, y: p.y / R }); });
    ensurePositions();
    renderGraph();
    var t0 = performance.now();
    showJobSoon(token, "Force layout · seed " + S.view.seed);
    var w = getWorker();
    if (w) {
      S.workerBusy = true;
      w.onmessage = function (ev) {
        var m = ev.data;
        if (!m || m.job !== token) return;
        if (m.type === "progress") { if (token === S.jobToken) $("jobProgress").value = m.progress; return; }
        var pos = new Map();
        for (var i = 0; i < m.ids.length; i++) pos.set(m.ids[i], { x: m.xy[2 * i], y: m.xy[2 * i + 1] });
        finishForce(token, pos, m.params, performance.now() - t0, "Web Worker", R, n, opts);
      };
      w.onerror = function (e) {
        if (e && e.preventDefault) e.preventDefault();
        S.worker = null; S.workerBusy = false; S.workerDisabled = true;
        log("layout", "Layout worker unavailable; computing on the main thread instead");
        if (token === S.jobToken) runForceMain(g, opts, token, R, pinned, t0);
      };
      w.postMessage({ type: "force", job: token, seed: S.view.seed, pinned: pinned,
        nodes: g.nodes.map(function (x) { return { id: x.id }; }),
        edges: g.edges.map(function (e) { return { from: e.from, to: e.to }; }) });
      return;
    }
    runForceMain(g, opts, token, R, pinned, t0);
  }
  /* Fallback (no Worker support, or file://): time-sliced on the main thread. */
  function runForceMain(g, opts, token, R, pinned, t0) {
    var n = g.nodes.length;
    var pin = new Map(pinned.map(function (p) { return [p.id, { x: p.x, y: p.y }]; }));
    var lay = C.createForceLayout(g.nodes, g.edges, { seed: S.view.seed, pinned: pin });
    function frame() {
      if (token !== S.jobToken) return;
      var start = performance.now();
      while (performance.now() - start < 24 && !lay.done()) lay.step(n > 800 ? 1 : 4);
      $("jobProgress").value = lay.progress();
      if (!lay.done()) { requestAnimationFrame(frame); return; }
      finishForce(token, lay.positions(), lay.params, performance.now() - t0, "main thread", R, n, opts);
    }
    requestAnimationFrame(frame);
  }
  function cancelJob() {
    S.jobToken++;
    clearTimeout(S.jobShowTimer);
    $("job").hidden = true;
    if (S.workerBusy && S.worker) { S.worker.terminate(); S.worker = null; S.workerBusy = false; }
  }

  function showLayoutNote(text) { var el = $("layoutNote"); el.textContent = text; el.hidden = false; }
  function hideLayoutNote() { $("layoutNote").hidden = true; }

  /* ───────────────────────── graph rendering ───────────────────────── */
  function shapePath(type, r) {
    var a, i, pts = [];
    function poly(k, rot, rr) { pts = []; for (i = 0; i < k; i++) { a = rot + (Math.PI * 2 * i) / k; pts.push((Math.cos(a) * rr).toFixed(2) + "," + (Math.sin(a) * rr).toFixed(2)); } return "M" + pts.join("L") + "Z"; }
    switch (type) {
      case "organization": return "M" + (-r * 0.86) + "," + (-r * 0.86) + "h" + (r * 1.72) + "v" + (r * 1.72) + "h" + (-r * 1.72) + "Z";
      case "ip": return poly(4, -Math.PI / 2, r * 1.12);
      case "certificate": return poly(6, 0, r * 1.02);
      case "document": return "M" + (-r * 0.75) + "," + (-r) + "h" + (r * 1.05) + "l" + (r * 0.45) + "," + (r * 0.45) + "v" + (r * 1.55) + "h" + (-r * 1.5) + "Z";
      case "system": return poly(3, -Math.PI / 2, r * 1.2);
      case "account": return poly(3, Math.PI / 2, r * 1.2);
      case "topic": return poly(8, Math.PI / 8, r);
      case "other": return "M" + (-r * 0.6) + "," + (-r * 0.6) + "h" + (r * 1.2) + "v" + (r * 1.2) + "h" + (-r * 1.2) + "Z";
      default: return "M" + (-r) + ",0a" + r + "," + r + " 0 1,0 " + (2 * r) + ",0a" + r + "," + r + " 0 1,0 " + (-2 * r) + ",0Z";
    }
  }

  function labelPriority() {
    var pr = new Map(), g = S.graph;
    var m = metricsForGraph();
    var ranked = g.nodes.slice().sort(function (a, b) { return (m.degree[b.id].total - m.degree[a.id].total) || (a.id < b.id ? -1 : 1); });
    var top = Math.max(3, Math.ceil(g.nodes.length * 0.15));
    ranked.forEach(function (n, i) { pr.set(n.id, i < top ? 1 : 2); });
    var sel = selectedEntityId();
    if (sel) {
      pr.set(sel, 0);
      g.edges.forEach(function (e) { if (e.from === sel) pr.set(e.to, 0); if (e.to === sel) pr.set(e.from, 0); });
    }
    if (S.view.focus) pr.set(S.resolver.canonicalOf(S.view.focus), 0);
    S.view.pinned.forEach(function (_p, id) { pr.set(id, 0); });
    return pr;
  }

  function edgeGeometry(e, a, b, offset) {
    var dx = b.x - a.x, dy = b.y - a.y, len = Math.sqrt(dx * dx + dy * dy) || 1;
    var nx = -dy / len, ny = dx / len;
    var cx = (a.x + b.x) / 2 + nx * offset, cy = (a.y + b.y) / 2 + ny * offset;
    var sx = a.x + (cx - a.x) / Math.max(1, Math.hypot(cx - a.x, cy - a.y)) * NODE_R;
    var sy = a.y + (cy - a.y) / Math.max(1, Math.hypot(cx - a.x, cy - a.y)) * NODE_R;
    var tx = b.x - (b.x - cx) / Math.max(1, Math.hypot(b.x - cx, b.y - cy)) * (NODE_R + (e.rel.directed ? 3 : 0));
    var ty = b.y - (b.y - cy) / Math.max(1, Math.hypot(b.x - cx, b.y - cy)) * (NODE_R + (e.rel.directed ? 3 : 0));
    var mx = 0.25 * sx + 0.5 * cx + 0.25 * tx, my = 0.25 * sy + 0.5 * cy + 0.25 * ty;
    return { d: "M" + sx.toFixed(1) + "," + sy.toFixed(1) + "Q" + cx.toFixed(1) + "," + cy.toFixed(1) + " " + tx.toFixed(1) + "," + ty.toFixed(1), mx: mx, my: my };
  }

  function renderGraph() {
    var svg = $("graph");
    clear(svg);
    S.nodeEls = new Map(); S.edgeEls = new Map();
    var g = S.graph;
    if (!g) return;
    if (!g.nodes.length) {
      setCanvasState("empty", S.ds.entities.length ? "No entities match the current filters" : "This dataset has no entities",
        S.ds.entities.length ? "Hidden records are not deleted. Clear the filters to show everything again." : null,
        S.ds.entities.length ? [btn("Show everything", clearFilters, "primary")] : null);
      return;
    }
    if (!$("canvasState").hidden && S.ds) setCanvasState(null);
    svg.setAttribute("data-dense", g.nodes.length <= 45 ? "0" : "1");
    var defs = sv("defs");
    [["arrow", "#7a8796"], ["arrow-conf", "#3fa596"], ["arrow-sel", "#38bdf8"], ["arrow-path", "#a78bfa"], ["arrow-disp", "#fbbf24"], ["arrow-rej", "#f87171"]].forEach(function (m) {
      defs.appendChild(sv("marker", { id: m[0], viewBox: "0 0 10 10", refX: "8", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" },
        sv("path", { d: "M0,1L9,5L0,9Z", fill: m[1] })));
    });
    svg.appendChild(defs);
    var vp = sv("g", { id: "vp" });
    svg.appendChild(vp);

    var meta = S.layoutMeta || {};
    var rings = sv("g", { class: "rings", "aria-hidden": "true" });
    if ((meta.mode === "focus-rings" || meta.mode === "type-sectors") && meta.R) {
      (meta.rings || []).forEach(function (r) {
        if (!r.radius) return;
        rings.appendChild(sv("circle", { class: "g-ring", cx: 0, cy: 0, r: (r.radius * meta.R).toFixed(1) }));
        if (r.label) rings.appendChild(sv("text", { class: "g-ring-label", x: 6, y: (-r.radius * meta.R - 8).toFixed(1) }, r.label + " · " + r.count));
      });
      (meta.sectors || []).forEach(function (s) {
        /* Inside the ring, anchored toward the centre, so node labels (which
           point outward) never collide with sector names. */
        var a = (s.start + s.end) / 2, rr = meta.R * (meta.rings && meta.rings.length > 1 ? 0.5 : 0.8);
        var cx = Math.cos(a);
        rings.appendChild(sv("text", { class: "g-sector-label", x: (cx * rr).toFixed(1), y: (Math.sin(a) * rr + 4).toFixed(1), "text-anchor": cx > 0.25 ? "end" : cx < -0.25 ? "start" : "middle" }, (TYPE_NAME[s.type] || s.type) + " · " + s.count));
      });
    }
    vp.appendChild(rings);

    var pairCount = new Map(), pairIndex = new Map();
    g.edges.forEach(function (e) { var k = [e.from, e.to].sort().join("|"); pairCount.set(k, (pairCount.get(k) || 0) + 1); });
    var edgesG = sv("g", { class: "edges" });
    /* Above 600 relationships each edge is a single path; labels and
       evidence badges are added on demand for selected/incident edges. */
    var lite = g.edges.length > 600;
    S.liteEdges = lite;
    g.edges.forEach(function (e) {
      var a = S.positions.get(e.from), b = S.positions.get(e.to);
      if (!a || !b) return;
      var grp = sv("g", { class: "edge-g", "data-id": e.id });
      var d, mx, my;
      if (e.from === e.to) {
        d = "M" + (a.x - 6) + "," + (a.y - NODE_R) + "C" + (a.x - 30) + "," + (a.y - 60) + " " + (a.x + 30) + "," + (a.y - 60) + " " + (a.x + 6) + "," + (a.y - NODE_R);
        mx = a.x; my = a.y - 48;
      } else {
        var k = [e.from, e.to].sort().join("|"), total = pairCount.get(k), i = pairIndex.get(k) || 0;
        pairIndex.set(k, i + 1);
        var sign = e.from < e.to ? 1 : -1;
        var off = total > 1 ? (i - (total - 1) / 2) * 26 * sign : 0;
        var geo = edgeGeometry(e, a, b, off);
        d = geo.d; mx = geo.mx; my = geo.my;
      }
      var rv = e.rel.review;
      var marker = rv === "confirmed" ? "arrow-conf" : rv === "disputed" ? "arrow-disp" : rv === "rejected" ? "arrow-rej" : "arrow";
      var line = sv("path", { class: "edge rv-e-" + rv, d: d, "marker-end": e.rel.directed ? "url(#" + marker + ")" : null, "data-marker": marker });
      grp.appendChild(line);
      grp.setAttribute("data-mx", mx.toFixed(1)); grp.setAttribute("data-my", my.toFixed(1));
      if (lite) grp.classList.add("lite");
      else { grp.appendChild(sv("path", { class: "edge-hit", d: d })); decorateEdge(grp, e); }
      edgesG.appendChild(grp);
      S.edgeEls.set(e.id, grp);
    });
    vp.appendChild(edgesG);

    var pr = labelPriority();
    var nodesG = sv("g", { class: "nodes" });
    var deg = metricsForGraph().degree;
    var order = keyboardOrder();
    if (!S.rovingId || !S.positions.has(S.rovingId)) S.rovingId = order[0] || null;
    g.nodes.forEach(function (n) {
      var p = S.positions.get(n.id);
      if (!p) return;
      var label = n.label;
      var aria = (TYPE_NAME[n.type] || n.type) + ": " + label + ". " + plural(deg[n.id].total, "relationship") + " in view" + (n.forced ? ". Hidden by filters; shown because it is selected" : "") + (n.members.length > 1 ? ". Merged from " + n.members.length + " records" : "");
      var grp = sv("g", { class: "node t-" + n.type, "data-id": n.id, transform: "translate(" + p.x.toFixed(1) + "," + p.y.toFixed(1) + ")", tabindex: n.id === S.rovingId ? "0" : "-1", role: "button", "aria-label": aria, "aria-pressed": "false" });
      grp.appendChild(sv("circle", { class: "halo", r: NODE_R + 6 }));
      if (n.members.length > 1) grp.appendChild(sv("circle", { class: "merged", r: NODE_R + 3 }));
      grp.appendChild(sv("path", { class: "shape", d: shapePath(n.type, NODE_R) }));
      grp.appendChild(sv("text", { class: "glyph", y: 0.5 }, GLYPH[n.type] || "OTH"));
      grp.appendChild(sv("circle", { class: "pin", cx: NODE_R * 0.8, cy: -NODE_R * 0.8, r: 3.5 }));
      var lp = labelPlacement(p);
      grp.appendChild(sv("text", { class: "lbl p" + (pr.get(n.id) || 2), x: lp.x, y: lp.y, "text-anchor": lp.anchor }, truncate(label, lp.max) + (n.forced ? " (hidden by filter)" : "")));
      nodesG.appendChild(grp);
      S.nodeEls.set(n.id, grp);
    });
    vp.appendChild(nodesG);
    if (S.ds.dataset.synthetic) {
      /* Watermark outside the viewport transform: always readable. */
      svg.appendChild(sv("text", { x: "99%", y: "98%", "text-anchor": "end", fill: "#7a8796", "font-size": "11", "font-family": "system-ui, sans-serif" }, "SYNTHETIC TRAINING DATA · not a real intelligence feed"));
    }
    applyZoom();
    updateClasses();
  }

  function decorateEdge(grp, e) {
    if (grp.querySelector(".ev-mark")) return;
    var mx = grp.getAttribute("data-mx"), my = grp.getAttribute("data-my");
    var nsup = e.rel.evidence.supporting.length, ncon = e.rel.evidence.contradicting.length;
    grp.appendChild(sv("circle", { class: "ev-mark", cx: mx, cy: my, r: 8 }));
    grp.appendChild(sv("text", { class: "ev-count", x: mx, y: my }, String(nsup) + (ncon ? "/" + ncon : "")));
    grp.appendChild(sv("text", { class: "edge-label", x: (+mx + 11).toFixed(1), y: (+my - 9).toFixed(1) }, e.rel.type.replace(/_/g, " ") + (e.rel.directed ? " →" : " ↔")));
    grp.appendChild(sv("title", null, labelOf(e.rel.from) + (e.rel.directed ? " → " : " — ") + e.rel.type + (e.rel.directed ? " → " : " — ") + labelOf(e.rel.to) + " (" + e.rel.review + "; " + nsup + " supporting, " + ncon + " contradicting)"));
  }

  /* Radial: labels point away from the centre. Hierarchy: labels sit under
     the node so neighbours in a row do not overlap. Force: to the right. */
  function labelPlacement(p) {
    var mode = (S.layoutMeta || {}).mode;
    if (mode === "hierarchical") return { x: 0, y: NODE_R + 14, anchor: "middle", max: 26 };
    if ((mode === "type-sectors" || mode === "focus-rings") && (p.x !== 0 || p.y !== 0)) {
      var len = Math.hypot(p.x, p.y) || 1, ux = p.x / len, uy = p.y / len;
      var off = NODE_R + 6;
      return { x: +(ux * off).toFixed(1), y: +(uy * off + 4).toFixed(1), anchor: ux < -0.2 ? "end" : ux > 0.2 ? "start" : "middle", max: 34 };
    }
    return { x: NODE_R + 6, y: 4, anchor: "start", max: 42 };
  }

  function selectedEntityId() {
    if (!S.selection) return null;
    if (S.selection.kind === "entity") return S.resolver.canonicalOf(S.selection.id);
    return null;
  }

  function updateClasses() {
    var selEnt = selectedEntityId();
    var selRel = S.selection && S.selection.kind === "relationship" ? S.selection.id : null;
    var focus = S.view.focus ? S.resolver.canonicalOf(S.view.focus) : null;
    var pathEdges = new Set(), pathNodes = new Set();
    if (S.activePath) S.activePath.steps.forEach(function (s) { pathEdges.add(s.relationship); pathNodes.add(s.from); pathNodes.add(s.to); });
    var neighbors = new Set(), incident = new Set();
    if (selEnt) {
      S.graph.edges.forEach(function (e) {
        if (e.from === selEnt || e.to === selEnt) { incident.add(e.id); neighbors.add(e.from); neighbors.add(e.to); }
      });
    }
    if (selRel) {
      var re = S.graph.edges.filter(function (e) { return e.id === selRel; })[0];
      if (re) { neighbors.add(re.from); neighbors.add(re.to); }
    }
    var dimming = !!(selEnt || selRel || S.activePath);
    var byId = new Map(S.graph.nodes.map(function (x) { return [x.id, x]; }));
    S.nodeEls.forEach(function (el, id) {
      var n = byId.get(id);
      el.classList.toggle("sel", id === selEnt);
      el.setAttribute("aria-pressed", id === selEnt ? "true" : "false");
      el.classList.toggle("focus", id === focus);
      el.classList.toggle("pinned", S.view.pinned.has(id));
      el.classList.toggle("forced", !!(n && n.forced));
      el.classList.toggle("path", pathNodes.has(id));
      el.classList.toggle("dim", dimming && !(id === selEnt || neighbors.has(id) || pathNodes.has(id)));
    });
    if (S.liteEdges) {
      var edgeById = new Map(S.graph.edges.map(function (e) { return [e.id, e]; }));
      incident.forEach(function (id) { var el = S.edgeEls.get(id); if (el) decorateEdge(el, edgeById.get(id)); });
      pathEdges.forEach(function (id) { var el = S.edgeEls.get(id); if (el) decorateEdge(el, edgeById.get(id)); });
      if (selRel && S.edgeEls.get(selRel)) decorateEdge(S.edgeEls.get(selRel), edgeById.get(selRel));
    }
    S.edgeEls.forEach(function (el, id) {
      var line = el.querySelector(".edge");
      var isSel = id === selRel, onPath = pathEdges.has(id), inc = incident.has(id);
      el.classList.toggle("sel", isSel);
      el.classList.toggle("path", onPath);
      el.classList.toggle("incident", inc && !isSel);
      el.classList.toggle("dim", dimming && !(isSel || onPath || inc));
      if (line.getAttribute("marker-end")) line.setAttribute("marker-end", "url(#" + (isSel ? "arrow-sel" : onPath ? "arrow-path" : line.getAttribute("data-marker")) + ")");
    });
    var lp = labelPriority();
    S.nodeEls.forEach(function (el, id) { var l = el.querySelector(".lbl"); if (l) l.setAttribute("class", "lbl p" + (lp.get(id) || 2)); });
    $("btnBack").disabled = !S.history.length;
    $("dockBack").disabled = !S.history.length;
  }

  /* ── zoom / pan ── */
  function canvasSize() { var r = $("canvas").getBoundingClientRect(); return { w: Math.max(1, r.width), h: Math.max(1, r.height) }; }
  function fitView() {
    if (!S.positions.size) return;
    /* Bounds include each label's estimated extent in the direction it is
       drawn (≈6.3 px per character at 11.5 px), so outward radial labels on
       the left are not clipped. */
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    var byId = new Map(S.graph.nodes.map(function (n) { return [n.id, n]; }));
    S.positions.forEach(function (p, id) {
      if (!S.nodeEls.has(id)) return;
      var lp = labelPlacement(p), n = byId.get(id);
      var w = Math.min(lp.max, n ? n.label.length : 10) * 6.3;
      var lx0 = lp.anchor === "start" ? p.x + lp.x : lp.anchor === "end" ? p.x + lp.x - w : p.x + lp.x - w / 2;
      minX = Math.min(minX, p.x - NODE_R, lx0); maxX = Math.max(maxX, p.x + NODE_R, lx0 + w);
      minY = Math.min(minY, p.y - NODE_R, p.y + lp.y - 12); maxY = Math.max(maxY, p.y + NODE_R, p.y + lp.y + 4);
    });
    if (!isFinite(minX)) return;
    var pad = 24;
    var c = canvasSize();
    var bw = (maxX - minX) + pad * 2, bh = (maxY - minY) + pad * 2;
    var k = Math.min(c.w / bw, c.h / bh);
    k = Math.max(0.04, Math.min(2.2, k));
    S.zoom.k = k; S.fitK = k;
    S.zoom.x = c.w / 2 - ((minX + maxX) / 2) * k;
    S.zoom.y = c.h / 2 - ((minY + maxY) / 2) * k;
    applyZoom();
  }
  function applyZoom() {
    var vp = $("vp");
    if (!vp) return;
    vp.setAttribute("transform", "translate(" + S.zoom.x.toFixed(1) + "," + S.zoom.y.toFixed(1) + ") scale(" + S.zoom.k.toFixed(4) + ")");
    var px = NODE_R * S.zoom.k;
    $("graph").setAttribute("data-zoom", px < 7 ? "far" : px < 13 ? "mid" : "near");
  }
  function zoomAt(factor, cx, cy) {
    var c = canvasSize();
    if (cx === undefined) { cx = c.w / 2; cy = c.h / 2; }
    var k2 = Math.max(0.03, Math.min(6, S.zoom.k * factor));
    S.zoom.x = cx - (cx - S.zoom.x) * (k2 / S.zoom.k);
    S.zoom.y = cy - (cy - S.zoom.y) * (k2 / S.zoom.k);
    S.zoom.k = k2;
    applyZoom();
  }
  function centerOn(id) {
    var p = S.positions.get(id);
    if (!p) return;
    var c = canvasSize();
    var visibleW = c.w, offsetY = 0;
    if (isMobile() && document.getElementById("app").getAttribute("data-sheet") !== "closed") offsetY = -c.h * 0.22;
    S.zoom.x = visibleW / 2 - p.x * S.zoom.k;
    S.zoom.y = c.h / 2 + offsetY - p.y * S.zoom.k;
    applyZoom();
  }
  function toWorld(clientX, clientY) {
    var r = $("canvas").getBoundingClientRect();
    return { x: (clientX - r.left - S.zoom.x) / S.zoom.k, y: (clientY - r.top - S.zoom.y) / S.zoom.k };
  }

  function bindCanvas() {
    var svg = $("graph"), pointers = new Map(), drag = null, pinch = null;
    svg.addEventListener("wheel", function (ev) {
      ev.preventDefault();
      var r = $("canvas").getBoundingClientRect();
      zoomAt(Math.exp(-ev.deltaY * 0.0015), ev.clientX - r.left, ev.clientY - r.top);
    }, { passive: false });
    svg.addEventListener("pointerdown", function (ev) {
      pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      try { svg.setPointerCapture(ev.pointerId); } catch (e) { /* synthetic or stale pointer */ }
      if (pointers.size === 2) {
        var pts = Array.from(pointers.values());
        pinch = { d: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y), k: S.zoom.k };
        drag = null;
        return;
      }
      var nodeEl = ev.target.closest && ev.target.closest(".node");
      var edgeEl = ev.target.closest && ev.target.closest(".edge-g");
      drag = { x0: ev.clientX, y0: ev.clientY, zx: S.zoom.x, zy: S.zoom.y, moved: false,
        node: nodeEl ? nodeEl.getAttribute("data-id") : null, edge: edgeEl ? edgeEl.getAttribute("data-id") : null };
    });
    svg.addEventListener("pointermove", function (ev) {
      if (!pointers.has(ev.pointerId)) return;
      pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (pinch && pointers.size === 2) {
        var pts = Array.from(pointers.values());
        var d = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
        var r = $("canvas").getBoundingClientRect();
        var cx = (pts[0].x + pts[1].x) / 2 - r.left, cy = (pts[0].y + pts[1].y) / 2 - r.top;
        zoomAt((pinch.k * d / pinch.d) / S.zoom.k, cx, cy);
        return;
      }
      if (!drag) return;
      var dx = ev.clientX - drag.x0, dy = ev.clientY - drag.y0;
      if (!drag.moved && Math.hypot(dx, dy) < 5) return;
      if (!drag.moved && drag.node) pushLayoutHistory("moved " + labelOf(drag.node));
      drag.moved = true;
      if (drag.node) {
        var w = toWorld(ev.clientX, ev.clientY);
        S.positions.set(drag.node, w);
        var el = S.nodeEls.get(drag.node);
        if (el) el.setAttribute("transform", "translate(" + w.x.toFixed(1) + "," + w.y.toFixed(1) + ")");
        redrawEdgesFor(drag.node);
      } else {
        svg.classList.add("panning");
        S.zoom.x = drag.zx + dx; S.zoom.y = drag.zy + dy;
        applyZoom();
      }
    });
    function end(ev) {
      pointers.delete(ev.pointerId);
      svg.classList.remove("panning");
      if (pinch) { if (pointers.size < 2) pinch = null; drag = null; return; }
      if (!drag) return;
      var d = drag; drag = null;
      if (ev.type === "pointercancel") return;
      if (d.moved && d.node) {
        S.view.pinned.set(d.node, S.positions.get(d.node));
        updateClasses(); saveView(); renderRail();
        log("layout", "Pinned " + d.node + " at a manual position");
        return;
      }
      if (d.moved) return;
      if (d.node) select({ kind: "entity", id: d.node });
      else if (d.edge) select({ kind: "relationship", id: d.edge });
      else if (S.selection) select(null);
    }
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", end);
    svg.addEventListener("keydown", onGraphKey);
    svg.addEventListener("focusin", function (ev) {
      var n = ev.target.closest && ev.target.closest(".node");
      if (n) S.rovingId = n.getAttribute("data-id");
    });
  }

  function redrawEdgesFor(id) {
    S.graph.edges.forEach(function (e) {
      if (e.from !== id && e.to !== id) return;
      var grp = S.edgeEls.get(e.id);
      if (!grp) return;
      var a = S.positions.get(e.from), b = S.positions.get(e.to);
      var geo = e.from === e.to ? null : edgeGeometry(e, a, b, 0);
      if (!geo) return;
      grp.querySelector(".edge").setAttribute("d", geo.d);
      grp.setAttribute("data-mx", geo.mx.toFixed(1)); grp.setAttribute("data-my", geo.my.toFixed(1));
      var hit = grp.querySelector(".edge-hit"); if (hit) hit.setAttribute("d", geo.d);
      var m = grp.querySelector(".ev-mark"); if (m) { m.setAttribute("cx", geo.mx.toFixed(1)); m.setAttribute("cy", geo.my.toFixed(1)); }
      var c = grp.querySelector(".ev-count"); if (c) { c.setAttribute("x", geo.mx.toFixed(1)); c.setAttribute("y", geo.my.toFixed(1)); }
      var l = grp.querySelector(".edge-label"); if (l) { l.setAttribute("x", (geo.mx + 11).toFixed(1)); l.setAttribute("y", (geo.my - 9).toFixed(1)); }
    });
  }

  function keyboardOrder() {
    return S.graph.nodes.slice().sort(function (a, b) {
      return (C.ENTITY_TYPES.indexOf(a.type) - C.ENTITY_TYPES.indexOf(b.type)) || (a.label.toLowerCase() < b.label.toLowerCase() ? -1 : a.label.toLowerCase() > b.label.toLowerCase() ? 1 : 0);
    }).map(function (n) { return n.id; });
  }
  function onGraphKey(ev) {
    var nodeEl = ev.target.closest && ev.target.closest(".node");
    if (!nodeEl) return;
    var id = nodeEl.getAttribute("data-id");
    var order = keyboardOrder(), i = order.indexOf(id);
    var next = null;
    if (ev.key === "ArrowRight" || ev.key === "ArrowDown") next = order[(i + 1) % order.length];
    else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") next = order[(i - 1 + order.length) % order.length];
    else if (ev.key === "Home") next = order[0];
    else if (ev.key === "End") next = order[order.length - 1];
    else if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select({ kind: "entity", id: id }); focusNode(id); return; }
    if (next) {
      ev.preventDefault();
      focusNode(next);
    }
  }
  function focusNode(id) {
    var prev = S.nodeEls.get(S.rovingId);
    if (prev) prev.setAttribute("tabindex", "-1");
    S.rovingId = id;
    var el = S.nodeEls.get(id);
    if (el) { el.setAttribute("tabindex", "0"); el.focus({ preventScroll: true }); ensureOnScreen(id); }
  }
  function ensureOnScreen(id) {
    var p = S.positions.get(id); if (!p) return;
    var c = canvasSize(), sx = p.x * S.zoom.k + S.zoom.x, sy = p.y * S.zoom.k + S.zoom.y;
    if (sx < 30 || sy < 30 || sx > c.w - 30 || sy > c.h - 30) centerOn(id);
  }

  /* ───────────────────────── legend ───────────────────────── */
  function renderLegend() {
    var el = clear($("legend"));
    el.appendChild(h("h4", null, "Entity types (shape + code)"));
    S.idx.entityTypes.forEach(function (t) {
      var s = sv("svg", { width: 26, height: 26, viewBox: "-14 -14 28 28", class: "t-" + t, "aria-hidden": "true" },
        sv("path", { d: shapePath(t, 10), fill: "#171e27", stroke: "currentColor", "stroke-width": "1.6" }));
      el.appendChild(h("div", { class: "li" }, s, h("span", { class: "tglyph t-" + t }, GLYPH[t]), TYPE_NAME[t] || t));
    });
    el.appendChild(h("h4", null, "Relationship review state (line + glyph)"));
    [["confirmed", "#3fa596", null], ["unreviewed", "#7a8796", "6 4"], ["disputed", "#fbbf24", "2 3"], ["rejected", "#f87171", "1 4"]].forEach(function (r) {
      var s = sv("svg", { width: 38, height: 12, "aria-hidden": "true" }, sv("line", { x1: 2, y1: 6, x2: 36, y2: 6, stroke: r[1], "stroke-width": 2, "stroke-dasharray": r[2] }));
      el.appendChild(h("div", { class: "li" }, s, h("span", { class: "rv rv-" + r[0] }, r[0])));
    });
    el.appendChild(h("h4", null, "Marks"));
    [["Cyan solid ring", "selected"], ["Teal dashed ring", "neighbourhood focus"], ["Violet outline", "on the highlighted path"], ["Amber dot", "pinned position"], ["Dashed outline", "hidden by filters, kept because selected"], ["Outer thin ring", "merged entity (analyst decision)"], ["Arrowhead", "directed relationship; ↔ = undirected"], ["Number on a link", "supporting / contradicting records (visible when zoomed in)"]].forEach(function (m) {
      el.appendChild(h("div", { class: "li" }, h("b", null, m[0]), " — " + m[1]));
    });
    el.appendChild(h("h4", null, "Keyboard"));
    el.appendChild(h("p", { class: "note" }, "Tab into the graph, then use the arrow keys to move between entities, Enter to select, Escape to clear. Press / to search, Alt+← to go back, F to fit."));
    el.appendChild(h("p", { class: "note" }, "Labels thin out as you zoom out. The selection, its neighbours, the focus and pinned entities stay labelled."));
  }

  /* ───────────────────────── selection + history ───────────────────────── */
  function snapshotContext() {
    return { selection: S.selection, focus: S.view.focus, hops: S.view.hops, filters: JSON.parse(JSON.stringify(S.view.filters)), layout: S.view.layout };
  }
  function select(sel, opts) {
    opts = opts || {};
    if (sel && S.selection && sel.kind === S.selection.kind && sel.id === S.selection.id) { openSheetFor(); return; }
    if (!opts.noHistory) { S.history.push(snapshotContext()); if (S.history.length > 60) S.history.shift(); }
    S.selection = sel;
    var needRecompute = false;
    if (sel && sel.kind === "entity") {
      var cid = S.resolver.canonicalOf(sel.id);
      S.selection = { kind: "entity", id: cid };
      if (!S.nodeEls.has(cid)) needRecompute = true;
    } else if (S.graph && S.graph.forced.length) needRecompute = true;
    if (needRecompute) recompute({ keepView: true }); else { updateClasses(); renderTimeline(); saveView(); }
    renderInspector();
    if (sel) { openSheetFor(); if (sel.kind === "entity" && opts.center) centerOn(S.selection.id); }
    else setSheet("closed");
  }
  function goBack() {
    var prev = S.history.pop();
    if (!prev) return;
    var changed = JSON.stringify([prev.focus, prev.hops, prev.filters, prev.layout]) !== JSON.stringify([S.view.focus, S.view.hops, S.view.filters, S.view.layout]);
    S.view.focus = prev.focus; S.view.hops = prev.hops; S.view.filters = prev.filters; S.view.layout = prev.layout;
    S.selection = prev.selection;
    if (changed) { renderLayoutSeg(); recompute({ fit: true }); renderRail(); } else { updateClasses(); renderTimeline(); }
    renderInspector();
    log("view", "Returned to the previous selection and view");
  }
  function setFocus(id, hops) {
    S.history.push(snapshotContext());
    S.view.focus = id; S.view.hops = hops;
    pushLayoutHistory("neighbourhood change");
    recompute({ fit: true });
    renderRail();
    log("view", hops ? "Isolated " + plural(hops, "hop") + " around " + id : "Cleared neighbourhood isolation");
  }
  function clearFilters() {
    S.history.push(snapshotContext());
    S.view.filters = { entityTypes: null, relTypes: null, review: null, window: null };
    S.view.focus = null; S.view.hops = 0;
    recompute({ fit: true });
    renderRail();
    log("view", "Cleared every filter and isolation; full dataset in view");
  }

  /* ───────────────────────── rail ───────────────────────── */
  function sec(title, count) {
    var s = h("section", { class: "sec" });
    s.appendChild(h("h3", null, title, count !== undefined ? h("span", { class: "ct" }, count) : null));
    return s;
  }
  function checkList(values, current, counts, onChange, labeller) {
    var wrap = h("div");
    values.forEach(function (v) {
      var on = !current || current.indexOf(v) !== -1;
      var cb = h("input", { type: "checkbox", checked: on, onchange: function () {
        var cur = current ? current.slice() : values.slice();
        if (cb.checked) { if (cur.indexOf(v) === -1) cur.push(v); } else cur = cur.filter(function (x) { return x !== v; });
        onChange(cur.length === values.length ? null : cur);
      } });
      wrap.appendChild(h("label", { class: "check" }, cb, labeller ? labeller(v) : v, counts ? h("span", { class: "ct" }, counts[v] || 0) : null));
    });
    return wrap;
  }
  function applyFilter(mut, what) {
    S.history.push(snapshotContext());
    mut(S.view.filters);
    recompute({ keepView: false });
    renderRail();
    log("view", "Filter changed: " + what);
  }

  function renderRail() {
    if (!S.ds) return;
    var body = clear($("railBody"));
    var f = S.view.filters;

    var scope = sec("Scope");
    scope.appendChild(h("p", { class: "note", id: "railScopeNote" }, describeScope()));
    var hopSeg = h("div", { class: "seg", role: "group", "aria-label": "Neighbourhood" });
    [[0, "All"], [1, "1 hop"], [2, "2 hops"]].forEach(function (o) {
      hopSeg.appendChild(h("button", { type: "button", "aria-pressed": String((S.view.focus ? S.view.hops : 0) === o[0]), onclick: function () {
        if (o[0] === 0) { setFocus(null, 0); return; }
        var id = selectedEntityId() || S.view.focus;
        if (!id) { toast("Select an entity first"); return; }
        setFocus(id, o[0]);
      } }, o[1]));
    });
    scope.appendChild(h("div", { class: "row" }, hopSeg, btn("Show everything", clearFilters)));
    scope.appendChild(h("p", { class: "note" }, S.view.focus ? "Isolated around " + labelOf(S.view.focus) + "." : "Choose 1 or 2 hops to isolate the selected entity's neighbourhood."));
    body.appendChild(scope);

    var typeCounts = {}, relCounts = {}, revCounts = {};
    S.ds.entities.forEach(function (e) { typeCounts[e.type] = (typeCounts[e.type] || 0) + 1; });
    S.ds.relationships.forEach(function (r) { relCounts[r.type] = (relCounts[r.type] || 0) + 1; revCounts[r.review] = (revCounts[r.review] || 0) + 1; });
    var types = sec("Entity types");
    types.appendChild(checkList(S.idx.entityTypes, f.entityTypes, typeCounts, function (v) { applyFilter(function (x) { x.entityTypes = v; }, "entity types"); },
      function (t) { return h("span", null, h("span", { class: "tglyph t-" + t }, GLYPH[t]), " ", TYPE_NAME[t] || t); }));
    body.appendChild(types);
    var rels = sec("Relationship types");
    rels.appendChild(checkList(S.idx.relTypes, f.relTypes, relCounts, function (v) { applyFilter(function (x) { x.relTypes = v; }, "relationship types"); },
      function (t) { return t.replace(/_/g, " "); }));
    body.appendChild(rels);
    var rev = sec("Evidence review state");
    rev.appendChild(checkList(C.REVIEW_STATES, f.review, revCounts, function (v) { applyFilter(function (x) { x.review = v; }, "review state"); },
      function (r) { return h("span", { class: "rv rv-" + r }, r); }));
    rev.appendChild(h("p", { class: "note" }, "Rejected relationships are hidden by default and counted in the scope strip."));
    body.appendChild(rev);

    var tw = sec("Time window");
    var from = h("input", { type: "date", value: f.window && f.window.from ? f.window.from.slice(0, 10) : "", "aria-label": "From date (UTC)" });
    var to = h("input", { type: "date", value: f.window && f.window.to ? f.window.to.slice(0, 10) : "", "aria-label": "To date (UTC)" });
    var unk = h("input", { type: "checkbox", checked: !!(f.window && f.window.includeUnknown) });
    tw.appendChild(h("label", { class: "field" }, h("span", null, "From (UTC)"), from));
    tw.appendChild(h("label", { class: "field" }, h("span", null, "To (UTC, inclusive)"), to));
    tw.appendChild(h("label", { class: "check" }, unk, "Include relationships whose timing is unknown or only partly known"));
    tw.appendChild(h("div", { class: "row" },
      btn("Apply window", function () {
        if (!from.value && !to.value) { toast("Choose at least one date"); return; }
        applyFilter(function (x) { x.window = { from: from.value ? from.value + "T00:00:00Z" : null, to: to.value ? to.value + "T23:59:59Z" : null, includeUnknown: unk.checked }; }, "time window");
      }, "sm primary"),
      f.window ? btn("Remove window", function () { applyFilter(function (x) { x.window = null; }, "time window removed"); }) : null));
    tw.appendChild(h("p", { class: "note" }, "Uses each relationship's first and last observed times. A missing end is not treated as ongoing."));
    body.appendChild(tw);

    var lay = sec("Layout");
    lay.appendChild(h("p", { class: "note" }, layoutDescription()));
    var seed = h("input", { type: "number", min: "0", step: "1", value: String(S.view.seed), "aria-label": "Force layout seed" });
    lay.appendChild(h("div", { class: "row" }, h("label", { class: "field grow" }, h("span", null, "Force layout seed"), seed),
      btn("Run force layout", function () {
        pushLayoutHistory("force re-run");
        S.view.seed = (parseInt(seed.value, 10) >>> 0) || 0;
        S.view.layout = "force"; renderLayoutSeg(); computeLayout({ fit: true }); saveView(); renderRail();
      })));
    if (S.view.pinned.size) {
      var pl = h("ul", { class: "linklist" });
      S.view.pinned.forEach(function (_p, id) {
        pl.appendChild(h("li", null, h("button", { type: "button", class: "linkbtn", onclick: function () { select({ kind: "entity", id: id }, { center: true }); } }, truncate(labelOf(id), 32)),
          btn("Unpin", function () { togglePin(id); }, "sm quiet")));
      });
      lay.appendChild(h("p", { class: "label" }, plural(S.view.pinned.size, "pinned position")));
      lay.appendChild(pl);
      lay.appendChild(btn("Unpin all", function () { pushLayoutHistory("unpin all"); S.view.pinned = new Map(); computeLayout({ keepView: true }); saveView(); renderRail(); }));
    } else lay.appendChild(h("p", { class: "note" }, "Drag an entity to pin it. Pins hold across layouts until removed."));
    body.appendChild(lay);

    body.appendChild(renderPathSection());
    body.appendChild(renderMetricsSection());
    body.appendChild(renderMergeSection());

    if (isMobile()) {
      var act = sec("Session activity");
      act.appendChild(btn("Show activity (" + S.events.length + ")", function () { closeRail(); toggleActivity(true); }));
      body.appendChild(act);
    }
  }
  function renderRailStatus() {
    var n = $("railScopeNote");
    if (n) n.textContent = describeScope();
    var stale = $("metricsStale");
    if (stale) {
      var run = S.findings.get(S.metricsRunId);
      stale.hidden = !(run && run.scopeKey !== scopeKey());
    }
  }
  function layoutDescription() {
    var m = S.layoutMeta || {};
    if (m.mode === "force") return "Force-directed, seed " + m.params.seed + ", " + m.params.iterations + " iterations" + (m.params.approximation ? ", " + m.params.approximation : "") + (m.where ? ", computed in " + m.where + " (" + m.runtime_ms + " ms)" : "") + ". Same seed and pins give the same layout.";
    if (m.mode === "hierarchical") return "Hierarchy of directed relationships: " + m.layers + " layers. Undirected links are drawn but do not set layers." + (m.unlinkedRow !== null ? " Entities with no directed links sit on the bottom row." : "");
    if (m.mode === "focus-rings") return "Radial rings by hop distance from " + labelOf(m.focus) + " (direction ignored).";
    if (m.mode === "type-sectors") return "Radial overview: one sector per entity type, ordered by type then name.";
    return "—";
  }
  function togglePin(id) {
    pushLayoutHistory(S.view.pinned.has(id) ? "unpin" : "pin");
    if (S.view.pinned.has(id)) S.view.pinned.delete(id);
    else { var p = S.positions.get(id); if (p) S.view.pinned.set(id, { x: p.x, y: p.y }); }
    updateClasses(); saveView(); renderRail(); renderInspector();
  }

  /* ── path analysis ── */
  var pathForm = { from: null, to: null, direction: "any", maxHops: 4, scope: "full", relTypes: null, review: DEFAULT_REVIEW.slice(), useWindow: false };
  function entityOptions(selected) {
    var opts = [h("option", { value: "" }, "— choose —")];
    var ents = S.ds.entities.filter(function (e) { return S.resolver.canonicalOf(e.id) === e.id; }).slice().sort(function (a, b) { return a.label.localeCompare(b.label); });
    ents.forEach(function (e) { opts.push(h("option", { value: e.id, selected: e.id === selected }, truncate(e.label, 48) + " · " + GLYPH[e.type])); });
    return opts;
  }
  function renderPathSection() {
    var s = sec("Path analysis");
    var fromSel = h("select", { "aria-label": "Path start", onchange: function () { pathForm.from = fromSel.value || null; } }, entityOptions(pathForm.from));
    var toSel = h("select", { "aria-label": "Path end", onchange: function () { pathForm.to = toSel.value || null; } }, entityOptions(pathForm.to));
    s.appendChild(h("label", { class: "field" }, h("span", null, "From"), fromSel));
    s.appendChild(h("label", { class: "field" }, h("span", null, "To"), toSel));
    var dir = h("select", { onchange: function () { pathForm.direction = dir.value; } },
      h("option", { value: "any", selected: pathForm.direction === "any" }, "Either direction"),
      h("option", { value: "forward", selected: pathForm.direction === "forward" }, "Follow arrow direction only"));
    var hops = h("select", { onchange: function () { pathForm.maxHops = +hops.value; } },
      [1, 2, 3, 4, 5, 6].map(function (n) { return h("option", { value: n, selected: pathForm.maxHops === n }, n + " max hops"); }));
    var scopeSel = h("select", { onchange: function () { pathForm.scope = scopeSel.value; } },
      h("option", { value: "full", selected: pathForm.scope === "full" }, "Search the full dataset"),
      h("option", { value: "visible", selected: pathForm.scope === "visible" }, "Search the visible subgraph only"));
    s.appendChild(h("div", { class: "row" }, h("label", { class: "field grow" }, h("span", null, "Direction"), dir), h("label", { class: "field" }, h("span", null, "Length"), hops)));
    s.appendChild(h("label", { class: "field" }, h("span", null, "Scope"), scopeSel));
    var det = h("details", null, h("summary", { class: "note" }, "Allowed relationship types and review states"));
    det.appendChild(checkList(S.idx.relTypes, pathForm.relTypes, null, function (v) { pathForm.relTypes = v; }, function (t) { return t.replace(/_/g, " "); }));
    det.appendChild(checkList(C.REVIEW_STATES, pathForm.review, null, function (v) { pathForm.review = v; }, function (r) { return h("span", { class: "rv rv-" + r }, r); }));
    var winCb = h("input", { type: "checkbox", checked: pathForm.useWindow, onchange: function () { pathForm.useWindow = winCb.checked; } });
    det.appendChild(h("label", { class: "check" }, winCb, "Apply the current time window"));
    s.appendChild(det);
    s.appendChild(h("div", { class: "row" },
      btn("Use selection as start", function () { var id = selectedEntityId(); if (!id) { toast("Select an entity first"); return; } pathForm.from = id; renderRail(); }, "sm quiet"),
      btn("as end", function () { var id = selectedEntityId(); if (!id) { toast("Select an entity first"); return; } pathForm.to = id; renderRail(); }, "sm quiet")));
    s.appendChild(btn("Find paths", runPathAnalysis, "sm primary"));
    var run = S.findings.get(S.pathRunId);
    if (run) {
      var r = run.result;
      var out = h("div", { class: "note", role: "status" });
      if (!r.reachable) out.appendChild(h("p", null, "No path within " + plural(r.params.maxHops, "hop") + " under these constraints (" + plural(r.eligibleEdges, "eligible relationship") + ")."));
      else {
        out.appendChild(h("p", null, plural(r.paths.length, "path") + " of " + plural(r.shortestLength, "hop") + (r.truncated ? " (list truncated)" : "") + ". Fewest hops is not strength, likelihood or cause."));
        var ul = h("ul", { class: "linklist" });
        r.paths.forEach(function (p, i) {
          var on = S.activePath === p;
          ul.appendChild(h("li", null,
            btn((on ? "● " : "") + "Path " + (i + 1), function () { S.activePath = on ? null : p; updateClasses(); renderRail(); }, "sm" + (on ? " primary" : "")),
            h("span", null, p.steps.map(function (st) { return st.type.replace(/_/g, " "); }).join(" · "))));
        });
        out.appendChild(ul);
      }
      out.appendChild(btn("Explain this result", function () { select({ kind: "finding", id: run.id }); }, "sm"));
      s.appendChild(out);
    }
    return s;
  }
  function runPathAnalysis() {
    if (!pathForm.from || !pathForm.to) { toast("Choose a start and an end"); return; }
    if (pathForm.from === pathForm.to) { toast("Start and end must differ"); return; }
    var edges = pathForm.scope === "visible" ? S.graph.edges : C.projectEdges(S.ds, S.resolver);
    var params = { from: S.resolver.canonicalOf(pathForm.from), to: S.resolver.canonicalOf(pathForm.to), direction: pathForm.direction, maxHops: pathForm.maxHops,
      relTypes: pathForm.relTypes, review: pathForm.review, window: pathForm.useWindow ? S.view.filters.window : null, limit: 20 };
    var run = C.runAnalysis({
      name: "Path analysis", algorithm: "Constrained breadth-first search (all fewest-hop paths)", params: Object.assign({ scope: pathForm.scope }, params),
      fingerprint: S.fp, scope: pathForm.scope === "visible" ? "visible subgraph — " + describeScope() : "full dataset" + (C.confirmedMergeGroups(S.nb, S.idx).length ? " with confirmed merges applied" : ""),
      limitations: ["Fewest hops under the stated constraints. It is not a measure of strength, likelihood, risk or causation.", "At most 20 paths are listed; a truncated result says so.", "Self-loops are ignored."]
    }, function () { return C.findPaths(edges, params); }, new Date());
    run.id = "run-" + (++S.runSeq); run.kind = "path"; run.include = true;
    run.summary = run.result.reachable ? plural(run.result.paths.length, "path") + " of " + plural(run.result.shortestLength, "hop") + " from " + labelOf(params.from) + " to " + labelOf(params.to) : "No qualifying path from " + labelOf(params.from) + " to " + labelOf(params.to);
    S.findings.set(run.id, run);
    S.pathRunId = run.id;
    S.activePath = run.result.paths[0] || null;
    if (S.activePath) {
      var vis = new Set(S.graph.edges.map(function (e) { return e.id; }));
      if (!S.activePath.steps.every(function (st) { return vis.has(st.relationship); })) {
        toast("Path uses relationships hidden by filters — showing everything");
        S.view.filters = { entityTypes: null, relTypes: null, review: null, window: S.view.filters.window }; S.view.focus = null; S.view.hops = 0;
        recompute({ keepView: true });
      }
    }
    updateClasses(); renderRail();
    log("analysis", "Path analysis " + run.id + ": " + run.summary + " (" + run.runtime_ms + " ms)");
  }

  /* ── metrics ── */
  function renderMetricsSection() {
    var s = sec("Graph metrics");
    s.appendChild(h("p", { class: "note" }, "Computed on the visible subgraph. Results change when filters change."));
    s.appendChild(btn("Compute for current scope", runMetrics, "sm primary"));
    var run = S.findings.get(S.metricsRunId);
    if (run) {
      var m = run.result;
      s.appendChild(h("p", { class: "note warn", id: "metricsStale", hidden: run.scopeKey === scopeKey() }, "Stale: filters, focus or merges changed since this was computed. Degree and components may differ in the current scope. Recompute to compare."));
      s.appendChild(h("dl", { class: "kv" },
        h("dt", null, "Entities"), h("dd", null, String(m.nodeCount)),
        h("dt", null, "Relationship records"), h("dd", null, String(m.edgeRecords)),
        h("dt", null, "Distinct pairs"), h("dd", null, String(m.distinctPairs)),
        h("dt", null, "Duplicates / self-loops"), h("dd", null, m.duplicateRecords + " / " + m.selfLoops),
        h("dt", null, "Density (undirected)"), h("dd", null, m.densityUndirected === null ? "undefined (n < 2)" : m.densityUndirected.toFixed(4)),
        h("dt", null, "Density (directed)"), h("dd", null, m.densityDirected === null ? "undefined (n < 2)" : m.densityDirected.toFixed(4)),
        h("dt", null, "Components"), h("dd", null, m.componentCount + " (largest " + m.largestComponent + ", " + m.isolated + " isolated)")));
      s.appendChild(h("p", { class: "label" }, "Most relationship records in scope"));
      var ul = h("ol", { class: "lim" });
      m.topByDegree.slice(0, 6).forEach(function (t) {
        ul.appendChild(h("li", null, h("button", { type: "button", class: "linkbtn", onclick: function () { select({ kind: "entity", id: t.id }, { center: true }); } }, truncate(labelOf(t.id), 30)), " — " + t.total + " records, " + t.distinctNeighbors + " neighbours"));
      });
      s.appendChild(ul);
      s.appendChild(h("p", { class: "note" }, C.METRIC_DEFINITIONS.caution));
      s.appendChild(btn("Explain this result", function () { select({ kind: "finding", id: run.id }); }, "sm"));
    }
    return s;
  }
  function runMetrics() {
    var g = S.graph;
    var run = C.runAnalysis({
      name: "Graph metrics", algorithm: "Degree counts, weakly connected components (union–find), undirected and directed density",
      params: { filters: S.view.filters, focus: S.view.focus, hops: S.view.hops, merges: C.confirmedMergeGroups(S.nb, S.idx).length },
      fingerprint: S.fp, scope: describeScope(), limitations: [C.METRIC_DEFINITIONS.caution, C.METRIC_DEFINITIONS.duplicates, "No community detection is run; none is configured."]
    }, function () { return C.computeMetrics(g.nodes, g.edges); }, new Date());
    run.id = "run-" + (++S.runSeq); run.kind = "metrics"; run.include = true; run.scopeKey = scopeKey();
    run.summary = run.result.nodeCount + " entities, " + run.result.edgeRecords + " records, " + run.result.componentCount + " components, directed density " + (run.result.densityDirected === null ? "undefined" : run.result.densityDirected.toFixed(4));
    var prev = S.findings.get(S.metricsRunId);
    if (prev) run.previous = { id: prev.id, scope: prev.scope, top: prev.result.topByDegree.slice(0, 5) };
    S.findings.set(run.id, run);
    S.metricsRunId = run.id;
    renderRail();
    log("analysis", "Graph metrics " + run.id + " (" + run.runtime_ms + " ms) on " + (S.graph.scope === "full" ? "full dataset" : "visible subgraph"));
  }

  /* ── entity resolution ── */
  function renderMergeSection() {
    var s = sec("Entity resolution", S.idx.merge.size);
    if (!S.idx.merge.size) { s.appendChild(h("p", { class: "note" }, "This dataset proposes no merge candidates.")); return s; }
    s.appendChild(h("p", { class: "note" }, "Candidates are proposals. Nothing merges until you confirm it with a rationale, and every decision can be undone."));
    S.idx.merge.forEach(function (m, id) {
      var state = C.mergeState(S.nb, id);
      var box = h("div", { class: "ev" });
      box.appendChild(h("div", { class: "row" }, h("span", { class: "tag" }, state), h("button", { type: "button", class: "linkbtn", onclick: function () { select({ kind: "merge", id: id }); } }, m.entities.map(labelOf).join(" + "))));
      box.appendChild(h("ul", { class: "lim" }, m.criteria.map(function (c) { return h("li", null, c); })));
      if (m.criteria.every(function (c) { return /name/i.test(c); })) box.appendChild(h("p", { class: "note warn" }, "Name similarity only. That alone is not grounds to merge."));
      box.appendChild(h("div", { class: "acts" }, mergeButtons(id, state)));
      s.appendChild(box);
    });
    return s;
  }
  function mergeButtons(id, state) {
    if (state === "candidate") return [
      btn("Confirm merge…", function () { decideMerge(id, "confirmed"); }, "sm"),
      btn("Reject…", function () { decideMerge(id, "rejected"); }, "sm quiet")
    ];
    return [btn("Undo decision", function () { decideMerge(id, "candidate"); }, "sm")];
  }
  function decideMerge(id, decision) {
    var apply = function (rationale) {
      try { S.nb = C.Notebook.decideMerge(S.nb, id, decision, rationale, new Date()); }
      catch (e) { toast(e.message); return; }
      saveNotebook(); refreshResolver();
      if (S.selection && S.selection.kind === "entity") S.selection.id = S.resolver.canonicalOf(S.selection.id);
      recompute({ keepView: true }); renderRail(); renderInspector();
      log("notebook", "Merge " + id + " → " + decision);
    };
    if (decision === "candidate") { apply(""); return; }
    promptText(decision === "confirmed" ? "Confirm merge" : "Reject merge", "Rationale", "Say why these records do or do not describe the same entity. The decision is appended to the notebook and can be undone.", apply);
  }

  /* ───────────────────────── tables ───────────────────────── */
  function renderTables() {
    var wrap = clear($("tables"));
    var tabs = h("div", { class: "seg", role: "group", "aria-label": "Table" });
    [["entities", "Entities"], ["relationships", "Relationships"], ["claims", "Claims"], ["sources", "Sources"]].forEach(function (t) {
      tabs.appendChild(h("button", { type: "button", "aria-pressed": String(S.view.tableTab === t[0]), onclick: function () { S.view.tableTab = t[0]; renderTables(); } }, t[1]));
    });
    wrap.appendChild(h("div", { class: "row" }, tabs, h("span", { class: "note" }, "Rows follow the current scope (" + (S.graph.scope === "full" ? "full dataset" : "visible subgraph") + "). Claims and sources always list the full dataset.")));
    var t = S.view.tableTab;
    if (t === "entities") wrap.appendChild(entityTable());
    else if (t === "relationships") wrap.appendChild(relationshipTable());
    else if (t === "claims") wrap.appendChild(claimTable());
    else wrap.appendChild(sourceTable());
  }
  function sortHeader(label, key) {
    var dir = S.sort.key === key ? S.sort.dir : 0;
    return h("th", { scope: "col", "aria-sort": dir === 1 ? "ascending" : dir === -1 ? "descending" : "none" },
      h("button", { type: "button", onclick: function () { S.sort = { key: key, dir: S.sort.key === key ? -S.sort.dir : 1 }; renderTables(); } }, label, dir ? (dir === 1 ? " ▲" : " ▼") : ""));
  }
  function entityTable() {
    var m = metricsForGraph();
    var rows = S.graph.nodes.map(function (n) { return { id: n.id, label: n.label, type: n.type, degree: m.degree[n.id].total, neighbors: m.degree[n.id].distinctNeighbors, members: n.members.length, forced: n.forced }; });
    var k = S.sort.key, d = S.sort.dir;
    rows.sort(function (a, b) { var x = a[k], y = b[k]; if (x === undefined) { x = a.label; y = b.label; } return (x < y ? -1 : x > y ? 1 : 0) * d; });
    var sel = selectedEntityId();
    var tb = h("tbody");
    rows.forEach(function (r) {
      tb.appendChild(h("tr", { class: r.id === sel ? "selrow" : null },
        h("td", null, h("button", { type: "button", class: "linkish", onclick: function () { select({ kind: "entity", id: r.id }); } }, r.label), r.forced ? h("span", { class: "tag" }, "hidden by filter") : null, r.members > 1 ? h("span", { class: "tag" }, "merged ×" + r.members) : null),
        h("td", null, h("span", { class: "tglyph t-" + r.type }, GLYPH[r.type]), " ", TYPE_NAME[r.type] || r.type),
        h("td", { class: "num" }, String(r.degree)), h("td", { class: "num" }, String(r.neighbors)), h("td", { class: "mono" }, r.id)));
    });
    return h("table", { class: "data" }, h("caption", null, plural(rows.length, "entity", "entities") + " in scope. Degree counts relationship records in scope."),
      h("thead", null, h("tr", null, sortHeader("Name", "label"), sortHeader("Type", "type"), sortHeader("Degree", "degree"), sortHeader("Neighbours", "neighbors"), sortHeader("ID", "id"))), tb);
  }
  function relationshipTable() {
    var tb = h("tbody");
    S.graph.edges.forEach(function (e) {
      var r = e.rel;
      tb.appendChild(h("tr", { class: S.selection && S.selection.id === r.id ? "selrow" : null },
        h("td", null, h("button", { type: "button", class: "linkish", onclick: function () { select({ kind: "relationship", id: r.id }); } }, labelOf(e.from) + (r.directed ? " → " : " — ") + labelOf(e.to))),
        h("td", null, r.type.replace(/_/g, " ")), h("td", null, r.directed ? "directed" : "undirected"),
        h("td", null, h("span", { class: "rv rv-" + r.review }, r.review)),
        h("td", { class: "num" }, r.evidence.supporting.length + " / " + r.evidence.contradicting.length),
        h("td", { class: "mono" }, (r.first_observed || "unknown") + " → " + (r.last_observed || "unknown"))));
    });
    return h("table", { class: "data" }, h("caption", null, plural(S.graph.edges.length, "relationship") + " in scope. Evidence column: supporting / contradicting records."),
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Relationship"), h("th", { scope: "col" }, "Type"), h("th", { scope: "col" }, "Direction"), h("th", { scope: "col" }, "Review"), h("th", { scope: "col" }, "Evidence"), h("th", { scope: "col" }, "Observed window"))), tb);
  }
  function claimTable() {
    var tb = h("tbody");
    S.ds.claims.forEach(function (c) {
      var L = LAYER_OF_CLAIM[c.kind];
      tb.appendChild(h("tr", { class: S.selection && S.selection.id === c.id ? "selrow" : null },
        h("td", null, h("button", { type: "button", class: "linkish", onclick: function () { select({ kind: "claim", id: c.id }); } }, c.statement)),
        h("td", null, h("span", { class: "layer " + L[0] }, L[1])), h("td", null, c.status), h("td", null, h("span", { class: "rv rv-" + c.review }, c.review)),
        h("td", { class: "num" }, c.evidence.supporting.length + " / " + c.evidence.contradicting.length)));
    });
    return h("table", { class: "data" }, h("caption", null, plural(S.ds.claims.length, "claim") + " in the dataset."),
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Statement"), h("th", { scope: "col" }, "Layer"), h("th", { scope: "col" }, "Status"), h("th", { scope: "col" }, "Review"), h("th", { scope: "col" }, "Evidence"))), tb);
  }
  function sourceTable() {
    var counts = {};
    S.ds.observations.forEach(function (o) { counts[o.source_id] = (counts[o.source_id] || 0) + 1; });
    var tb = h("tbody");
    S.ds.sources.forEach(function (s) {
      tb.appendChild(h("tr", { class: S.selection && S.selection.id === s.id ? "selrow" : null },
        h("td", null, h("button", { type: "button", class: "linkish", onclick: function () { select({ kind: "source", id: s.id }); } }, s.title)),
        h("td", null, s.kind), h("td", null, s.assessment.reliability), h("td", { class: "mono" }, s.independence_group), h("td", { class: "num" }, String(counts[s.id] || 0))));
    });
    return h("table", { class: "data" }, h("caption", null, plural(S.ds.sources.length, "source") + ". Sources that share an independence group are not independent of each other."),
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Source"), h("th", { scope: "col" }, "Kind"), h("th", { scope: "col" }, "Reliability"), h("th", { scope: "col" }, "Independence group"), h("th", { scope: "col" }, "Records"))), tb);
  }

  /* ───────────────────────── timeline ───────────────────────── */
  function relatedObservations() {
    var sel = S.selection, ids = new Set();
    if (!sel) return ids;
    if (sel.kind === "entity") S.resolver.membersOf(sel.id).forEach(function (m) { (S.idx.obsByEntity.get(m) || []).forEach(function (o) { ids.add(o.id); }); });
    else if (sel.kind === "relationship" || sel.kind === "claim") { var ref = C.relRefs(S.idx, sel.kind, sel.id); if (ref) ref.supporting.concat(ref.contradicting).forEach(function (x) { ids.add(x); }); }
    else if (sel.kind === "observation") ids.add(sel.id);
    else if (sel.kind === "source") S.ds.observations.forEach(function (o) { if (o.source_id === sel.id) ids.add(o.id); });
    return ids;
  }
  function renderTimeline() {
    var el = clear($("timeline"));
    if (!S.idx) return;
    var ext = S.idx.timeExtent;
    el.appendChild(h("span", { class: "label" }, "Observed"));
    if (ext.min === null) { el.appendChild(h("span", { class: "note" }, "No dated observations — history is unavailable for this dataset.")); return; }
    var span = Math.max(1, ext.max - ext.min);
    var col = h("div");
    var track = h("div", { class: "tl-track" });
    var win = S.view.filters.window;
    if (win) {
      var a = win.from ? Math.max(0, (Date.parse(win.from) - ext.min) / span) : 0, b = win.to ? Math.min(1, (Date.parse(win.to) - ext.min) / span) : 1;
      if (b > 0 && a < 1) { var w = h("div", { class: "tl-win", title: "Time window filter" }); w.style.left = (a * 100) + "%"; w.style.width = Math.max(0.3, (b - a) * 100) + "%"; track.appendChild(w); }
    }
    var rel = relatedObservations();
    var obs = S.ds.observations.filter(function (o) { return C.timeValue(o.observed_at) !== null; });
    if (obs.length > 400) obs = obs.filter(function (o, i) { return rel.has(o.id) || i % Math.ceil(obs.length / 400) === 0; });
    obs.forEach(function (o) {
      var x = (C.timeValue(o.observed_at) - ext.min) / span;
      var m = h("button", { type: "button", class: "tl-mark" + (rel.has(o.id) ? " on" : ""), "aria-label": o.id + ", observed " + fmtTime(o.observed_at) + (rel.has(o.id) ? ", related to selection" : ""), title: o.id + " · observed " + fmtTime(o.observed_at), onclick: function () { select({ kind: "observation", id: o.id }); } });
      m.style.left = (x * 100) + "%";
      track.appendChild(m);
    });
    col.appendChild(track);
    col.appendChild(h("div", { class: "tl-axis" }, h("span", null, new Date(ext.min).toISOString().slice(0, 10)), h("span", null, "observation time (not collection or ingestion time)"), h("span", null, new Date(ext.max).toISOString().slice(0, 10))));
    el.appendChild(col);
    el.appendChild(h("span", { class: "note" }, S.idx.undatedObservations ? plural(S.idx.undatedObservations, "undated record") + " not placed" : "all records dated"));
  }

  /* ───────────────────────── inspector ───────────────────────── */
  var SECTIONS = [["summary", "Summary"], ["evidence", "Evidence"], ["counter", "Counterevidence"], ["provenance", "Provenance"], ["time", "Time"], ["analysis", "Analysis"], ["limits", "Limitations"], ["actions", "Actions"]];
  function isec(key, title, count) {
    var s = h("section", { class: "isec", id: "isec-" + key, "aria-labelledby": "isec-h-" + key });
    s.appendChild(h("h3", { id: "isec-h-" + key }, title, count !== undefined ? h("span", { class: "ct" }, count) : null));
    return s;
  }
  function citeBtn(id) {
    var k = C.kindOf(S.idx, id) || (S.findings.has(id) ? "finding" : null);
    if (!k) return h("span", { class: "cite missing", title: "Not in the current dataset" }, id);
    var kind = k === "merge_candidate" ? "merge" : k;
    return h("button", { type: "button", class: "cite", onclick: function () { select({ kind: kind, id: id }); }, title: labelOf(id) }, id);
  }
  function entityLink(id) {
    return h("button", { type: "button", class: "linkbtn", onclick: function () { select({ kind: "entity", id: id }, { center: true }); } }, labelOf(id));
  }
  function summaryBlock(sentences) {
    var b = h("div", { class: "sum" });
    sentences.forEach(function (s) { b.appendChild(h("p", null, s.text, " ", s.cites.slice(0, 8).map(citeBtn), s.cites.length > 8 ? " +" + (s.cites.length - 8) : null)); });
    b.appendChild(h("p", { class: "gen" }, "Rule-based summary built from the records above. No AI model is configured."));
    return b;
  }
  function inInvestigation(id) { return S.nb.evidence.some(function (e) { return e.id === id; }); }
  function toggleEvidence(id) {
    if (inInvestigation(id)) S.nb = C.Notebook.detachEvidence(S.nb, id, new Date());
    else S.nb = C.Notebook.attachEvidence(S.nb, id, "", new Date());
    saveNotebook();
    log("notebook", (inInvestigation(id) ? "Attached " : "Detached ") + id);
    renderInspector(); if (S.mode === "investigate") renderInvestigate();
    toast(inInvestigation(id) ? "Added to investigation" : "Removed from investigation");
  }
  function evidenceCard(x, role) {
    if (x.missing) return h("div", { class: "ev" }, h("span", { class: "cite missing" }, x.id), " is cited but is not in this dataset.");
    var o = x.observation, s = x.source;
    var card = h("article", { class: "ev " + (role === "contra" ? "contra" : "support"), "aria-label": (role === "contra" ? "Contradicting" : "Supporting") + " evidence " + o.id });
    card.appendChild(h("div", { class: "row" }, h("span", { class: "layer observed" }, "OBSERVED"), citeBtn(o.id), role === "contra" ? h("span", { class: "rv rv-disputed" }, "contradicts") : null));
    card.appendChild(h("p", { class: "ex" }, o.excerpt));
    card.appendChild(h("div", { class: "meta" },
      h("span", null, h("b", null, "Source "), s ? s.title : "unknown"),
      s ? h("span", null, h("b", null, "Reliability "), s.assessment.reliability) : null,
      h("span", null, h("b", null, "Location "), o.location || "not recorded"),
      h("span", null, h("b", null, "Observed "), fmtTime(o.observed_at)),
      h("span", null, h("b", null, "Extraction "), o.extraction.method + (o.extraction.version ? " " + o.extraction.version : "") + (o.extraction.confidence !== null ? " · confidence " + o.extraction.confidence + " (supplied by extractor)" : ""))));
    card.appendChild(h("div", { class: "acts" },
      btn(inInvestigation(o.id) ? "Remove from investigation" : "Add to investigation", function () { toggleEvidence(o.id); }, "sm" + (inInvestigation(o.id) ? "" : " primary")),
      btn("Annotate", function () { annotate(o.id); }, "sm quiet"),
      btn("Open record", function () { select({ kind: "observation", id: o.id }); }, "sm quiet")));
    return card;
  }
  function facets(a, review, extra) {
    var f = h("div", { class: "facets" });
    function facet(k, v, sub, unknown) { f.appendChild(h("div", { class: "facet" }, h("div", { class: "k" }, k), h("div", { class: "v" + (unknown ? " unknown" : "") }, v), sub ? h("div", { class: "s" }, sub) : null)); }
    facet("Extraction confidence", a.extraction.supplied.length ? a.extraction.supplied.map(function (x) { return x.confidence; }).join(", ") : "not supplied",
      a.extraction.supplied.length ? "As reported by the extractor for " + plural(a.extraction.supplied.length, "record") + "; not calibrated here." : "No extractor reported a confidence. Unknown, not zero.", !a.extraction.supplied.length);
    var rel = a.sources.map(function (s) { return s.reliability; });
    facet("Source assessment", rel.length ? Array.from(new Set(rel)).join(", ") : "unknown", a.sources.length ? a.sources.map(function (s) { return s.reliability + ": " + truncate(s.basis, 70); }).slice(0, 2).join(" · ") : "No source attached.", !rel.length);
    facet("Independent corroboration", plural(a.corroboration.independentGroups, "group") + " / " + plural(a.corroboration.records, "record"),
      a.corroboration.dependentRecords ? plural(a.corroboration.dependentRecords, "record") + " share an upstream source and are not counted twice." : "Each supporting record comes from a distinct source group.");
    var fresh = a.freshness.latestObserved;
    facet("Freshness", fresh ? fmtTime(fresh) : "unknown",
      fresh && S.ds.dataset.as_of ? "Latest observation, " + dayDiff(fresh, S.ds.dataset.as_of) + " days before the dataset's as-of date." + (a.freshness.undated ? " " + plural(a.freshness.undated, "record") + " undated." : "") : (a.freshness.undated ? plural(a.freshness.undated, "record") + " have no observation time." : null), !fresh);
    facet("Analyst review", review || "not applicable", review ? reviewMeaning(review) : "Observations are not reviewed individually here.", !review);
    var model = a.extraction.methods.filter(function (m) { return /^model/.test(m); });
    facet("Model uncertainty", model.length ? "model-extracted" : "not applicable", model.length ? "Extracted by " + model.join(", ") + ". This workspace has no calibration for that model's confidence." : "No record here was produced by a model.", !model.length);
    if (extra) f.appendChild(extra);
    return f;
  }
  function reviewMeaning(r) {
    return { confirmed: "An analyst reviewed the evidence and accepted the link.", unreviewed: "Not yet reviewed by an analyst.", disputed: "An analyst marked the link as contested.", rejected: "An analyst rejected the link; it is hidden by default." }[r] || "";
  }
  function annotationsFor(id) {
    var list = S.nb.annotations.filter(function (a) { return a.target === id; });
    if (!list.length) return null;
    return h("div", null, list.map(function (a) { return h("div", { class: "annot" }, h("span", { class: "layer analyst" }, "ANALYST-ASSESSED"), " ", a.text, h("div", { class: "when" }, a.created_at)); }));
  }
  function annotate(id) {
    promptText("Annotate " + id, "Annotation", "Annotations are analyst judgements. They are saved to the investigation notebook and included in the brief.", function (text) {
      try { S.nb = C.Notebook.addAnnotation(S.nb, id, text, new Date()); } catch (e) { toast(e.message); return; }
      saveNotebook(); renderInspector(); if (S.mode === "investigate") renderInvestigate();
      log("notebook", "Annotated " + id);
    });
  }
  function compareBlock(collection, id) {
    if (!S.compare) return null;
    var d = S.compare.diff.collections[collection];
    var box = h("div", { class: "ev" }, h("p", { class: "label" }, "Snapshot comparison · v" + S.compare.diff.from.version + " → v" + S.compare.diff.to.version));
    var mod = d.modified.filter(function (m) { return m.id === id; })[0];
    if (d.notPresent.indexOf(id) !== -1) box.appendChild(h("p", null, "Not present in the later snapshot. That does not mean the underlying fact was deleted."));
    else if (mod) {
      box.appendChild(h("p", null, "Changed fields: " + mod.fields.join(", ") + "."));
      mod.fields.forEach(function (f) { box.appendChild(h("p", { class: "mono" }, f + ": " + truncate(JSON.stringify(mod.before[f]), 160) + " → " + truncate(JSON.stringify(mod.after[f]), 160))); });
      if (mod.fields.length === 1 && mod.fields[0] === "extraction") box.appendChild(h("p", { class: "note" }, "Extraction change only: same source record, different processing."));
    } else box.appendChild(h("p", null, "Unchanged in the later snapshot."));
    return box;
  }

  function inspectorHead(kindKey, title, ids, tags) {
    var head = clear($("inspHead"));
    head.appendChild(h("div", { class: "kind" }, h("span", { class: "tag" }, KIND_LABEL[kindKey] || kindKey), tags || null, h("span", { class: "grow" }),
      isMobile() ? btn("Close", function () { setSheet("closed"); }, "sm quiet") : null));
    head.appendChild(h("h2", { tabindex: "-1", id: "inspTitle" }, title));
    if (ids) head.appendChild(h("div", { class: "ids" }, ids));
  }
  function inspectorNav(keys) {
    var nav = clear($("inspNav"));
    SECTIONS.forEach(function (s) {
      if (keys && keys.indexOf(s[0]) === -1) return;
      nav.appendChild(h("a", { href: "#isec-" + s[0], onclick: function (ev) { ev.preventDefault(); var t = $("isec-" + s[0]); if (t) t.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" }); } }, s[1]));
    });
  }

  function renderInspector() {
    var body = clear($("inspBody"));
    $("inspBody").scrollTop = 0;
    var sel = S.selection;
    if (!S.ds) { clear($("inspHead")); clear($("inspNav")); return; }
    if (!sel) {
      clear($("inspHead")).appendChild(h("h2", null, "Evidence inspector"));
      clear($("inspNav"));
      body.appendChild(h("div", { class: "empty-insp" },
        h("p", null, "Select an entity or a relationship in the graph, a row in the table, or a search result."),
        h("p", { class: "note" }, "Every selection opens the same sections: summary, evidence, counterevidence, provenance, time, analysis, limitations and actions."),
        h("p", { class: "note" }, "Dataset: " + S.ds.dataset.title + (S.ds.dataset.synthetic ? " — synthetic training data. Every record is fictional." : ""))));
      updateDock();
      return;
    }
    var fn = { entity: inspectEntity, relationship: inspectRelationship, claim: inspectClaim, observation: inspectObservation, source: inspectSource, finding: inspectFinding, merge: inspectMerge }[sel.kind];
    if (fn) fn(body, sel.id);
    updateDock();
  }

  function inspectEntity(body, id) {
    var cid = S.resolver.canonicalOf(id);
    var e = S.idx.entity.get(cid);
    if (!e) { body.appendChild(h("p", { class: "note err" }, "Entity " + id + " is not in this dataset.")); return; }
    var members = S.resolver.membersOf(cid);
    var node = S.graph.nodes.filter(function (n) { return n.id === cid; })[0];
    inspectorHead("entity", e.label, members.join(" + "), [h("span", { class: "tglyph t-" + e.type }, GLYPH[e.type]), h("span", { class: "tag" }, TYPE_NAME[e.type] || e.type)]);
    inspectorNav();
    var rels = [], obs = [], claims = [];
    members.forEach(function (m) {
      (S.idx.relsByEntity.get(m) || []).forEach(function (r) { if (rels.indexOf(r) === -1) rels.push(r); });
      (S.idx.obsByEntity.get(m) || []).forEach(function (o) { if (obs.indexOf(o) === -1) obs.push(o); });
      (S.idx.claimsByEntity.get(m) || []).forEach(function (c) { if (claims.indexOf(c) === -1) claims.push(c); });
    });
    var visible = new Set(S.graph.edges.map(function (x) { return x.id; }));

    var s1 = isec("summary", "Summary");
    s1.appendChild(summaryBlock(C.summarize(S.idx, "entity", cid, S.resolver)));
    var ul = h("ul", { class: "linklist", "aria-label": "Relationships" });
    rels.forEach(function (r) {
      var from = S.resolver.canonicalOf(r.from), to = S.resolver.canonicalOf(r.to);
      var outward = from === cid;
      ul.appendChild(h("li", null,
        h("button", { type: "button", class: "linkbtn", onclick: function () { select({ kind: "relationship", id: r.id }); } },
          (outward ? "→ " : "← ") + r.type.replace(/_/g, " ") + (r.directed ? "" : " (undirected)") + " " + (outward ? labelOf(to) : labelOf(from))),
        h("span", { class: "rv rv-" + r.review }, r.review), visible.has(r.id) ? null : h("span", { class: "tag" }, "hidden")));
    });
    if (rels.length) { s1.appendChild(h("p", { class: "label" }, "Relationships")); s1.appendChild(ul); }
    if (claims.length) {
      s1.appendChild(h("p", { class: "label" }, "Claims about this entity"));
      s1.appendChild(h("ul", { class: "linklist" }, claims.map(function (c) { var L = LAYER_OF_CLAIM[c.kind]; return h("li", null, h("span", { class: "layer " + L[0] }, L[1]), h("button", { type: "button", class: "linkbtn", onclick: function () { select({ kind: "claim", id: c.id }); } }, truncate(c.statement, 110))); })));
    }
    var attrs = Object.keys(e.attributes);
    if (attrs.length || e.aliases.length) {
      var dl = h("dl", { class: "kv" });
      e.aliases.forEach(function (a) { add(dl, [h("dt", null, "Alias"), h("dd", null, a)]); });
      attrs.forEach(function (k) { add(dl, [h("dt", null, k), h("dd", null, e.attributes[k] === null ? "unknown" : String(e.attributes[k]), restrictedKey(k) ? h("span", { class: "tag" }, "restricted from export") : null)]); });
      s1.appendChild(dl);
    }
    var ann = annotationsFor(cid); if (ann) s1.appendChild(ann);
    body.appendChild(s1);

    var refs = { supporting: obs.map(function (o) { return o.id; }), contradicting: [] };
    var a = C.assessEvidence(S.idx, refs);
    var s2 = isec("evidence", "Evidence", obs.length);
    s2.appendChild(facets(a, null));
    if (!obs.length) s2.appendChild(h("p", { class: "note" }, "No observation mentions this entity."));
    a.supporting.forEach(function (x) { s2.appendChild(evidenceCard(x, "support")); });
    body.appendChild(s2);

    var s3 = isec("counter", "Counterevidence");
    var contra = [];
    rels.forEach(function (r) { r.evidence.contradicting.forEach(function (o) { contra.push({ o: o, via: r.id }); }); });
    claims.forEach(function (c) { c.evidence.contradicting.forEach(function (o) { contra.push({ o: o, via: c.id }); }); });
    if (!contra.length) s3.appendChild(h("p", { class: "note" }, "No contradicting records are attached to this entity's relationships or claims. Absence of counterevidence is not confirmation."));
    contra.forEach(function (c) {
      var x = C.assessEvidence(S.idx, { supporting: [c.o], contradicting: [] }).supporting[0];
      s3.appendChild(h("p", { class: "note" }, "Contradicts ", citeBtn(c.via)));
      s3.appendChild(evidenceCard(x, "contra"));
    });
    body.appendChild(s3);

    var s4 = isec("provenance", "Provenance");
    var dl2 = h("dl", { class: "kv" });
    add(dl2, [h("dt", null, "Record IDs"), h("dd", null, members.map(citeBtn))]);
    add(dl2, [h("dt", null, "Original IDs"), h("dd", null, members.map(function (m) { var x = S.idx.entity.get(m); return x.original_ids.length ? x.original_ids.join(", ") : "none recorded"; }).join(" · "))]);
    add(dl2, [h("dt", null, "Sources"), h("dd", null, e.source_ids.length ? e.source_ids.map(citeBtn) : "none listed")]);
    s4.appendChild(dl2);
    if (members.length > 1) {
      s4.appendChild(h("p", { class: "note" }, "Shown as one entity because an analyst confirmed a merge. The surviving ID is the alphabetically first member; all original records are kept."));
      S.idx.merge.forEach(function (m, mid) {
        if (C.mergeState(S.nb, mid) === "confirmed" && m.entities.indexOf(cid) !== -1) s4.appendChild(h("div", { class: "row" }, citeBtn(mid), btn("Undo merge", function () { decideMerge(mid, "candidate"); }, "sm")));
      });
    }
    S.idx.merge.forEach(function (m, mid) {
      var touches = m.entities.some(function (x) { return members.indexOf(x) !== -1; });
      if (!touches || C.mergeState(S.nb, mid) === "confirmed") return;
      s4.appendChild(h("div", { class: "ev" }, h("p", { class: "label" }, "Merge candidate · " + C.mergeState(S.nb, mid)), h("p", null, m.entities.map(labelOf).join(" + ")), h("ul", { class: "lim" }, m.criteria.map(function (c) { return h("li", null, c); })), h("div", { class: "acts" }, mergeButtons(mid, C.mergeState(S.nb, mid)))));
    });
    body.appendChild(s4);

    var s5 = isec("time", "Time");
    var dated = obs.filter(function (o) { return o.observed_at; }).map(function (o) { return o.observed_at; }).sort();
    var coll = obs.filter(function (o) { return o.collected_at; }).map(function (o) { return o.collected_at; }).sort();
    s5.appendChild(h("dl", { class: "kv" },
      h("dt", null, "Observed"), h("dd", null, dated.length ? fmtTime(dated[0]) + " → " + fmtTime(dated[dated.length - 1]) : "unknown"),
      h("dt", null, "Collected"), h("dd", null, coll.length ? fmtTime(coll[0]) + " → " + fmtTime(coll[coll.length - 1]) : "unknown"),
      h("dt", null, "Undated records"), h("dd", null, String(obs.length - dated.length))));
    s5.appendChild(h("p", { class: "note" }, "Observed = when the event happened according to the source. Collected = when the source captured it. Ingested = when it entered this dataset. They are kept separate."));
    var cb = compareBlock("entities", cid); if (cb) s5.appendChild(cb);
    body.appendChild(s5);

    var s6 = isec("analysis", "Analysis");
    if (node) {
      var m = metricsForGraph().degree[cid];
      s6.appendChild(h("dl", { class: "kv" },
        h("dt", null, "Degree in scope"), h("dd", null, m.total + " records (" + m.out + " out, " + m.in + " in, " + m.undirected + " undirected)"),
        h("dt", null, "Distinct neighbours"), h("dd", null, String(m.distinctNeighbors)),
        h("dt", null, "Scope"), h("dd", null, S.graph.scope === "full" ? "full dataset" : "visible subgraph")));
      s6.appendChild(h("p", { class: "note" }, C.METRIC_DEFINITIONS.degree + " " + C.METRIC_DEFINITIONS.caution));
    } else s6.appendChild(h("p", { class: "note" }, "Not in the current view, so no in-scope metrics."));
    body.appendChild(s6);

    var s7 = isec("limits", "Limitations");
    var lim = h("ul", { class: "lim" });
    var unrev = rels.filter(function (r) { return r.review === "unreviewed"; }).length;
    if (unrev) lim.appendChild(h("li", null, plural(unrev, "relationship") + " not yet reviewed."));
    if (obs.length - dated.length) lim.appendChild(h("li", null, plural(obs.length - dated.length, "record") + " without an observation time."));
    if (node && node.typeConflict) lim.appendChild(h("li", null, "Merged records disagree on the entity type."));
    if (node && node.forced) lim.appendChild(h("li", null, "Hidden by the current filters; shown only because it is selected."));
    if (a.corroboration.dependentRecords) lim.appendChild(h("li", null, plural(a.corroboration.dependentRecords, "record") + " repeat an upstream source."));
    if (S.ds.dataset.synthetic) lim.appendChild(h("li", null, "Synthetic dataset: this entity is fictional."));
    if (!lim.children.length) lim.appendChild(h("li", null, "No specific gaps detected by the workspace rules. That is not a guarantee of completeness."));
    s7.appendChild(lim);
    body.appendChild(s7);

    var s8 = isec("actions", "Actions");
    s8.appendChild(h("div", { class: "exports" },
      btn("Isolate 1 hop", function () { setFocus(cid, 1); }), btn("Isolate 2 hops", function () { setFocus(cid, 2); }),
      btn(S.view.pinned.has(cid) ? "Unpin" : "Pin position", function () { togglePin(cid); }),
      btn("Center", function () { centerOn(cid); }),
      btn("Annotate", function () { annotate(cid); }),
      btn("Add all evidence to investigation", function () { obs.forEach(function (o) { if (!inInvestigation(o.id)) S.nb = C.Notebook.attachEvidence(S.nb, o.id, "", new Date()); }); saveNotebook(); renderInspector(); toast(plural(obs.length, "record") + " in investigation"); log("notebook", "Attached evidence for " + cid); }),
      btn("Path start", function () { pathForm.from = cid; openRailSection(); }), btn("Path end", function () { pathForm.to = cid; openRailSection(); }),
      btn("Export evidence manifest", function () { exportManifest(obs.map(function (o) { return o.id; }), cid); })));
    body.appendChild(s8);
  }
  function restrictedKey(k) { return (S.ds.dataset.export_policy.restricted_attribute_keys || []).indexOf(k) !== -1; }
  function openRailSection() { renderRail(); if (isMobile()) openRail(); toast("Path endpoint set"); }

  function inspectRelationship(body, id) {
    var r = S.idx.relationship.get(id);
    if (!r) { body.appendChild(h("p", { class: "note err" }, "Relationship " + id + " is not in this dataset.")); return; }
    inspectorHead("relationship", labelOf(r.from) + (r.directed ? " → " : " — ") + r.type.replace(/_/g, " ") + (r.directed ? " → " : " — ") + labelOf(r.to), r.id,
      [h("span", { class: "rv rv-" + r.review }, r.review), h("span", { class: "tag" }, r.directed ? "directed" : "undirected")]);
    inspectorNav();
    var a = C.assessEvidence(S.idx, r.evidence);
    var s1 = isec("summary", "Summary");
    s1.appendChild(h("dl", { class: "kv" },
      h("dt", null, "From"), h("dd", null, entityLink(r.from)),
      h("dt", null, "To"), h("dd", null, entityLink(r.to)),
      h("dt", null, "Direction"), h("dd", null, r.directed ? "Directed: reads from \"" + labelOf(r.from) + "\" to \"" + labelOf(r.to) + "\"." : "Undirected: no direction is implied."),
      h("dt", null, "Meaning"), h("dd", null, r.semantics || "No semantics recorded.")));
    s1.appendChild(summaryBlock(C.summarize(S.idx, "relationship", id, S.resolver)));
    var ann = annotationsFor(id); if (ann) s1.appendChild(ann);
    body.appendChild(s1);
    var s2 = isec("evidence", "Evidence", r.evidence.supporting.length);
    s2.appendChild(facets(a, r.review));
    if (!r.evidence.supporting.length) s2.appendChild(h("p", { class: "note warn" }, "No supporting record is attached. The relationship rests on no evidence in this dataset."));
    a.supporting.forEach(function (x) { s2.appendChild(evidenceCard(x, "support")); });
    body.appendChild(s2);
    var s3 = isec("counter", "Counterevidence", r.evidence.contradicting.length);
    if (!r.evidence.contradicting.length) s3.appendChild(h("p", { class: "note" }, "No contradicting records attached. Absence of counterevidence is not confirmation."));
    a.contradicting.forEach(function (x) { s3.appendChild(evidenceCard(x, "contra")); });
    body.appendChild(s3);
    var s4 = isec("provenance", "Provenance");
    s4.appendChild(h("dl", { class: "kv" },
      h("dt", null, "Derivation"), h("dd", null, r.derivation || "Recorded directly from the cited observations."),
      h("dt", null, "Sources"), h("dd", null, a.sources.length ? a.sources.map(function (s) { return citeBtn(s.id); }) : "none"),
      h("dt", null, "Source groups"), h("dd", null, a.corroboration.groups.map(function (g) { return g.group + " (" + g.records.length + ")"; }).join(", ") || "none")));
    body.appendChild(s4);
    var s5 = isec("time", "Time");
    s5.appendChild(h("dl", { class: "kv" },
      h("dt", null, "First observed"), h("dd", null, fmtTime(r.first_observed)),
      h("dt", null, "Last observed"), h("dd", null, fmtTime(r.last_observed) + (r.first_observed && !r.last_observed ? " — the end is unknown; it is not assumed to be ongoing" : "")),
      h("dt", null, "In time window"), h("dd", null, S.view.filters.window ? ({ yes: "yes", no: "no", unknown: "uncertain (depends on an unknown time)" })[C.windowOverlap(r, S.view.filters.window)] : "no window set")));
    var tl = h("ul", { class: "linklist" });
    r.evidence.supporting.concat(r.evidence.contradicting).forEach(function (oid) {
      var o = S.idx.observation.get(oid); if (!o) return;
      tl.appendChild(h("li", { class: "mono" }, citeBtn(oid), "observed " + fmtTime(o.observed_at) + " · collected " + fmtTime(o.collected_at) + " · ingested " + fmtTime(o.ingested_at)));
    });
    s5.appendChild(tl);
    var cb = compareBlock("relationships", id); if (cb) s5.appendChild(cb);
    body.appendChild(s5);
    var s6 = isec("analysis", "Analysis");
    var onPath = S.activePath && S.activePath.steps.some(function (st) { return st.relationship === id; });
    s6.appendChild(h("p", { class: "note" }, onPath ? "This relationship is a step on the highlighted path. That only means it satisfies the path constraints." : "Not on a highlighted path."));
    if (r.type === "co_resolved" || /co_?occur/.test(r.type)) s6.appendChild(h("p", { class: "note warn" }, "Co-occurrence is not coordination or common control."));
    body.appendChild(s6);
    var s7 = isec("limits", "Limitations");
    var lim = h("ul", { class: "lim" });
    if (a.corroboration.independentGroups <= 1) lim.appendChild(h("li", null, "Rests on at most one independent source group."));
    if (a.corroboration.dependentRecords) lim.appendChild(h("li", null, plural(a.corroboration.dependentRecords, "supporting record") + " repeat an upstream source; they are not independent confirmation."));
    if (a.extraction.methods.some(function (m) { return /^model/.test(m); })) lim.appendChild(h("li", null, "Some evidence was extracted by a model and may contain extraction errors."));
    if (!r.first_observed && !r.last_observed) lim.appendChild(h("li", null, "When this relationship held is unknown."));
    if (r.review !== "confirmed") lim.appendChild(h("li", null, "Review state is " + r.review + "."));
    if (a.missing.length) lim.appendChild(h("li", null, plural(a.missing.length, "cited record") + " missing from the dataset."));
    if (!lim.children.length) lim.appendChild(h("li", null, "No specific gaps detected by the workspace rules."));
    s7.appendChild(lim);
    body.appendChild(s7);
    var s8 = isec("actions", "Actions");
    s8.appendChild(h("div", { class: "exports" },
      btn("Annotate", function () { annotate(id); }),
      btn("Add evidence to investigation", function () { r.evidence.supporting.concat(r.evidence.contradicting).forEach(function (o) { if (!inInvestigation(o) && S.idx.observation.has(o)) S.nb = C.Notebook.attachEvidence(S.nb, o, "", new Date()); }); saveNotebook(); renderInspector(); toast("Evidence added to investigation"); log("notebook", "Attached evidence for " + id); }),
      btn("Select source entity", function () { select({ kind: "entity", id: r.from }, { center: true }); }),
      btn("Select target entity", function () { select({ kind: "entity", id: r.to }, { center: true }); }),
      btn("Hide this type", function () { applyFilter(function (x) { x.relTypes = (x.relTypes || S.idx.relTypes.slice()).filter(function (t) { return t !== r.type; }); }, "hid " + r.type); }),
      btn("Export evidence manifest", function () { exportManifest(r.evidence.supporting.concat(r.evidence.contradicting), id); })));
    body.appendChild(s8);
  }

  function inspectClaim(body, id) {
    var c = S.idx.claim.get(id);
    if (!c) { body.appendChild(h("p", { class: "note err" }, "Claim " + id + " is not in this dataset.")); return; }
    var L = LAYER_OF_CLAIM[c.kind];
    inspectorHead("claim", c.statement, c.id, [h("span", { class: "layer " + L[0] }, L[1]), h("span", { class: "tag" }, c.status), h("span", { class: "rv rv-" + c.review }, c.review)]);
    inspectorNav();
    var a = C.assessEvidence(S.idx, c.evidence);
    var s1 = isec("summary", "Summary");
    s1.appendChild(h("p", null, "About: ", c.about.map(function (x) { return entityLink(x); }).reduce(function (acc, el, i) { if (i) acc.push(", "); acc.push(el); return acc; }, [])));
    s1.appendChild(summaryBlock(C.summarize(S.idx, "claim", id, S.resolver)));
    if (c.kind === "hypothesized") s1.appendChild(h("p", { class: "note warn" }, "A hypothesis recorded in the dataset: a candidate explanation, not an established fact."));
    var ann = annotationsFor(id); if (ann) s1.appendChild(ann);
    body.appendChild(s1);
    var s2 = isec("evidence", "Evidence", c.evidence.supporting.length);
    s2.appendChild(facets(a, c.review));
    a.supporting.forEach(function (x) { s2.appendChild(evidenceCard(x, "support")); });
    body.appendChild(s2);
    var s3 = isec("counter", "Counterevidence", c.evidence.contradicting.length);
    if (!c.evidence.contradicting.length) s3.appendChild(h("p", { class: "note" }, "No contradicting records attached."));
    a.contradicting.forEach(function (x) { s3.appendChild(evidenceCard(x, "contra")); });
    body.appendChild(s3);
    var s4 = isec("provenance", "Provenance");
    s4.appendChild(h("dl", { class: "kv" }, h("dt", null, "Derivation"), h("dd", null, c.derivation ? c.derivation.method : "Stated directly against the cited records."),
      h("dt", null, "Inputs"), h("dd", null, c.derivation ? c.derivation.inputs.map(citeBtn) : "—")));
    body.appendChild(s4);
    var s5 = isec("time", "Time");
    s5.appendChild(h("p", null, "Latest supporting observation: " + fmtTime(a.freshness.latestObserved) + ". " + (a.freshness.undated ? plural(a.freshness.undated, "record") + " undated." : "")));
    var cb = compareBlock("claims", id); if (cb) s5.appendChild(cb);
    body.appendChild(s5);
    var s6 = isec("analysis", "Analysis");
    s6.appendChild(h("p", { class: "note" }, "Status \"" + c.status + "\" comes from the dataset author. The workspace does not convert evidence counts into probabilities."));
    body.appendChild(s6);
    var s7 = isec("limits", "Limitations");
    var lim = h("ul", { class: "lim" });
    if (a.corroboration.dependentRecords) lim.appendChild(h("li", null, plural(a.corroboration.dependentRecords, "record") + " share an upstream source."));
    if (c.status === "unresolved") lim.appendChild(h("li", null, "Unresolved: the evidence does not settle this claim."));
    if (a.extraction.methods.some(function (m) { return /^model/.test(m); })) lim.appendChild(h("li", null, "Includes model-extracted evidence."));
    if (!lim.children.length) lim.appendChild(h("li", null, "No specific gaps detected by the workspace rules."));
    s7.appendChild(lim);
    body.appendChild(s7);
    var s8 = isec("actions", "Actions");
    s8.appendChild(h("div", { class: "exports" }, btn("Annotate", function () { annotate(id); }),
      btn("Add evidence to investigation", function () { c.evidence.supporting.concat(c.evidence.contradicting).forEach(function (o) { if (!inInvestigation(o) && S.idx.observation.has(o)) S.nb = C.Notebook.attachEvidence(S.nb, o, "", new Date()); }); saveNotebook(); renderInspector(); toast("Evidence added to investigation"); }),
      btn("Export evidence manifest", function () { exportManifest(c.evidence.supporting.concat(c.evidence.contradicting), id); })));
    body.appendChild(s8);
  }

  function inspectObservation(body, id) {
    var o = S.idx.observation.get(id);
    if (!o) { body.appendChild(h("p", { class: "note err" }, "Record " + id + " is not in this dataset.")); return; }
    var s = S.idx.source.get(o.source_id);
    inspectorHead("observation", truncate(o.excerpt, 120), o.id, [h("span", { class: "layer observed" }, "OBSERVED"), inInvestigation(id) ? h("span", { class: "tag" }, "in investigation") : null]);
    inspectorNav();
    var a = C.assessEvidence(S.idx, { supporting: [id], contradicting: [] });
    var s1 = isec("summary", "Summary");
    s1.appendChild(h("p", { class: "ev" }, h("span", { class: "ex" }, o.excerpt)));
    s1.appendChild(h("p", null, "About: ", o.about.map(entityLink).reduce(function (acc, el, i) { if (i) acc.push(", "); acc.push(el); return acc; }, [])));
    var ann = annotationsFor(id); if (ann) s1.appendChild(ann);
    body.appendChild(s1);
    var s2 = isec("evidence", "Evidence");
    s2.appendChild(facets(a, null));
    var cited = S.idx.citedBy.get(id) || [];
    s2.appendChild(h("p", { class: "label" }, "Cited by"));
    s2.appendChild(cited.length ? h("ul", { class: "linklist" }, cited.map(function (c) { return h("li", null, citeBtn(c.id), c.role); })) : h("p", { class: "note" }, "Not cited by any relationship or claim."));
    body.appendChild(s2);
    var s3 = isec("counter", "Counterevidence");
    var contraRoles = cited.filter(function (c) { return c.role === "contradicting"; });
    s3.appendChild(h("p", { class: "note" }, contraRoles.length ? "This record contradicts " + plural(contraRoles.length, "item") + " listed above." : "This record contradicts nothing in the dataset."));
    body.appendChild(s3);
    var s4 = isec("provenance", "Provenance");
    s4.appendChild(h("dl", { class: "kv" },
      h("dt", null, "Source"), h("dd", null, s ? citeBtn(s.id) : "unknown", s ? " " + s.title : ""),
      h("dt", null, "Location in source"), h("dd", null, o.location || "not recorded"),
      h("dt", null, "Extraction"), h("dd", null, o.extraction.method + (o.extraction.version ? " · " + o.extraction.version : " · version not recorded")),
      h("dt", null, "Extraction confidence"), h("dd", null, o.extraction.confidence === null ? "not supplied" : o.extraction.confidence + " (as reported by the extractor)"),
      h("dt", null, "Excerpt SHA-256"), h("dd", { class: "mono" }, C.sha256Hex(o.excerpt))));
    body.appendChild(s4);
    var s5 = isec("time", "Time");
    s5.appendChild(h("dl", { class: "kv" },
      h("dt", null, "Observed"), h("dd", null, fmtTime(o.observed_at) + (o.observed_at ? "" : " — the source gives no single observation time")),
      h("dt", null, "Collected"), h("dd", null, fmtTime(o.collected_at)),
      h("dt", null, "Ingested"), h("dd", null, fmtTime(o.ingested_at))));
    if (o.observed_at && o.collected_at && dayDiff(o.observed_at, o.collected_at) > 30) s5.appendChild(h("p", { class: "note" }, "Collected " + dayDiff(o.observed_at, o.collected_at) + " days after it was observed: new to the dataset is not the same as new activity."));
    var cb = compareBlock("observations", id); if (cb) s5.appendChild(cb);
    body.appendChild(s5);
    var s6 = isec("analysis", "Analysis");
    s6.appendChild(h("p", { class: "note" }, "Raw evidence. Assess it against each hypothesis in Investigate mode."));
    body.appendChild(s6);
    var s7 = isec("limits", "Limitations");
    var lim = h("ul", { class: "lim" });
    if (!o.observed_at) lim.appendChild(h("li", null, "No observation time."));
    if (o.extraction.method === "model") lim.appendChild(h("li", null, "Model-extracted: the excerpt may misrepresent the source."));
    if (s && /^(C|D|E|F|unknown)$/.test(s.assessment.reliability)) lim.appendChild(h("li", null, "Source reliability " + s.assessment.reliability + ": " + s.assessment.basis));
    if (!lim.children.length) lim.appendChild(h("li", null, "No specific gaps detected by the workspace rules."));
    s7.appendChild(lim);
    body.appendChild(s7);
    var s8 = isec("actions", "Actions");
    s8.appendChild(h("div", { class: "exports" },
      btn(inInvestigation(id) ? "Remove from investigation" : "Add to investigation", function () { toggleEvidence(id); }, "sm" + (inInvestigation(id) ? "" : " primary")),
      btn("Annotate", function () { annotate(id); }),
      btn("Export evidence manifest", function () { exportManifest([id], id); })));
    body.appendChild(s8);
  }

  function inspectSource(body, id) {
    var s = S.idx.source.get(id);
    if (!s) { body.appendChild(h("p", { class: "note err" }, "Source " + id + " is not in this dataset.")); return; }
    inspectorHead("source", s.title, s.id, [h("span", { class: "tag" }, "reliability " + s.assessment.reliability)]);
    inspectorNav(["summary", "evidence", "provenance", "limits"]);
    var obs = S.ds.observations.filter(function (o) { return o.source_id === id; });
    var sibling = S.ds.sources.filter(function (x) { return x.independence_group === s.independence_group && x.id !== id; });
    var s1 = isec("summary", "Summary");
    s1.appendChild(h("dl", { class: "kv" },
      h("dt", null, "Kind"), h("dd", null, s.kind),
      h("dt", null, "Reliability"), h("dd", null, s.assessment.reliability),
      h("dt", null, "Assessment basis"), h("dd", null, s.assessment.basis),
      h("dt", null, "Independence group"), h("dd", null, s.independence_group),
      h("dt", null, "Collected"), h("dd", null, fmtTime(s.collected_at)),
      h("dt", null, "Link"), h("dd", null, s.uri ? h("a", { href: s.uri, target: "_blank", rel: "noopener noreferrer", title: "Opens an external site in a new tab" }, s.uri, " ↗") : "none")));
    if (s.uri) s1.appendChild(h("p", { class: "note" }, "External link: opening it leaves this workspace and contacts that site." + (S.ds.dataset.synthetic ? " Reserved .example addresses do not resolve." : "")));
    body.appendChild(s1);
    var s2 = isec("evidence", "Records from this source", obs.length);
    s2.appendChild(h("ul", { class: "linklist" }, obs.map(function (o) { return h("li", null, citeBtn(o.id), truncate(o.excerpt, 90)); })));
    body.appendChild(s2);
    var s4 = isec("provenance", "Provenance");
    s4.appendChild(h("p", { class: "note" }, sibling.length ? "Shares independence group \"" + s.independence_group + "\" with " + sibling.map(function (x) { return x.title; }).join(", ") + ". Records from these sources are not independent confirmation of each other." : "No other source shares this independence group."));
    body.appendChild(s4);
    var s7 = isec("limits", "Limitations");
    s7.appendChild(h("ul", { class: "lim" }, h("li", null, "Reliability ratings come from the dataset author. The workspace does not re-assess them.")));
    body.appendChild(s7);
  }

  function inspectMerge(body, id) {
    var m = S.idx.merge.get(id);
    if (!m) return;
    var state = C.mergeState(S.nb, id);
    inspectorHead("merge", m.entities.map(labelOf).join(" + "), id, [h("span", { class: "tag" }, state)]);
    inspectorNav(["summary", "provenance", "actions"]);
    var s1 = isec("summary", "Summary");
    s1.appendChild(h("p", null, "Candidate match between: ", m.entities.map(function (e) { return citeBtn(e); })));
    s1.appendChild(h("p", { class: "label" }, "Match criteria"));
    s1.appendChild(h("ul", { class: "lim" }, m.criteria.map(function (c) { return h("li", null, c); })));
    body.appendChild(s1);
    var s4 = isec("provenance", "Decision history");
    var hist = S.nb.merge_decisions.filter(function (d) { return d.candidate === id; });
    s4.appendChild(hist.length ? h("ul", { class: "lim" }, hist.map(function (d) { return h("li", null, d.at + " — " + d.decision + ": " + d.rationale); })) : h("p", { class: "note" }, "No decision yet. Candidates never merge automatically."));
    body.appendChild(s4);
    var s8 = isec("actions", "Actions");
    s8.appendChild(h("div", { class: "exports" }, mergeButtons(id, state)));
    body.appendChild(s8);
  }

  function inspectFinding(body, id) {
    var run = S.findings.get(id);
    if (!run) { body.appendChild(h("p", { class: "note" }, "This finding is no longer available. Findings last for this session.")); return; }
    inspectorHead("finding", run.name + " — explain this result", run.id, [h("span", { class: "layer derived" }, "DERIVED")]);
    inspectorNav(["summary", "analysis", "limits", "actions"]);
    var s1 = isec("summary", "Result");
    s1.appendChild(h("p", null, run.summary));
    if (run.kind === "path") {
      var r = run.result;
      if (!r.reachable) s1.appendChild(h("p", { class: "note" }, "No path qualified. " + plural(r.eligibleEdges, "relationship") + " met the constraints; " + plural(r.exploredNodes, "entity", "entities") + " were reached within " + plural(r.params.maxHops, "hop") + "."));
      r.paths.forEach(function (p, i) {
        var box = h("div", { class: "ev" }, h("p", { class: "label" }, "Path " + (i + 1) + " · " + plural(p.length, "step")));
        var ol = h("ol", { class: "lim" });
        p.steps.forEach(function (st) {
          ol.appendChild(h("li", null, labelOf(st.from) + " → " + labelOf(st.to) + " via ", citeBtn(st.relationship),
            h("div", { class: "note" }, "Qualifies because: type \"" + st.type + "\" is allowed; review \"" + st.review + "\" is allowed; traversed " + (st.traversal === "forward" ? "along the arrow" : st.traversal === "reverse" ? "against the arrow (either-direction search)" : "an undirected link") + (r.params.window ? "; inside the time window" : "") + ". Evidence: " + st.supporting + " supporting, " + st.contradicting + " contradicting.")));
        });
        box.appendChild(ol);
        box.appendChild(btn(S.activePath === p ? "Highlighted" : "Highlight on graph", function () { S.activePath = p; updateClasses(); renderInspector(); }, "sm"));
        s1.appendChild(box);
      });
      s1.appendChild(h("p", { class: "note warn" }, "A fewest-hop path is not the strongest, most likely, safest or causal path. No such model is defined here."));
    }
    if (run.kind === "metrics") {
      var m = run.result;
      s1.appendChild(h("dl", { class: "kv" },
        h("dt", null, "Entities"), h("dd", null, String(m.nodeCount)), h("dt", null, "Records"), h("dd", null, String(m.edgeRecords)),
        h("dt", null, "Distinct pairs"), h("dd", null, String(m.distinctPairs)), h("dt", null, "Duplicates"), h("dd", null, String(m.duplicateRecords)),
        h("dt", null, "Self-loops"), h("dd", null, String(m.selfLoops)), h("dt", null, "Components"), h("dd", null, String(m.componentCount))));
      if (run.previous) {
        s1.appendChild(h("p", { class: "label" }, "Compared with the previous run (" + run.previous.id + ")"));
        s1.appendChild(h("p", { class: "note" }, "Previous scope: " + run.previous.scope));
        s1.appendChild(h("p", { class: "note" }, "Previous top entities: " + run.previous.top.map(function (t) { return labelOf(t.id) + " (" + t.total + ")"; }).join(", ")));
        s1.appendChild(h("p", { class: "note" }, "If the ranking differs, it is because the scope differs: degree counts only relationships in scope."));
      }
    }
    body.appendChild(s1);
    var s6 = isec("analysis", "Method and inputs");
    s6.appendChild(h("dl", { class: "kv" },
      h("dt", null, "Algorithm"), h("dd", null, run.algorithm),
      h("dt", null, "Version"), h("dd", null, "core " + run.core_version + " · algorithm " + run.algorithm_version),
      h("dt", null, "Parameters"), h("dd", { class: "mono" }, C.canonicalJSON(run.params)),
      h("dt", null, "Scope"), h("dd", null, run.scope || "—"),
      h("dt", null, "Dataset"), h("dd", { class: "mono" }, run.dataset_fingerprint),
      h("dt", null, "Seed"), h("dd", null, run.seed === null ? "not applicable (deterministic)" : String(run.seed)),
      h("dt", null, "Approximation"), h("dd", null, run.approximation || "none"),
      h("dt", null, "Executed"), h("dd", null, run.executed_at),
      h("dt", null, "Runtime"), h("dd", null, run.runtime_ms + " ms in this browser")));
    if (run.kind === "metrics") Object.keys(C.METRIC_DEFINITIONS).forEach(function (k) { s6.appendChild(h("p", { class: "note" }, C.METRIC_DEFINITIONS[k])); });
    body.appendChild(s6);
    var s7 = isec("limits", "Limitations");
    s7.appendChild(h("ul", { class: "lim" }, run.limitations.map(function (l) { return h("li", null, l); })));
    body.appendChild(s7);
    var s8 = isec("actions", "Actions");
    var inc = h("input", { type: "checkbox", checked: run.include, onchange: function () { run.include = inc.checked; if (S.mode === "brief") renderBrief(); } });
    s8.appendChild(h("label", { class: "check" }, inc, "Include in the brief's Methods section"));
    body.appendChild(s8);
  }

  /* ───────────────────────── investigate mode ───────────────────────── */
  function nbUpdate(fn, what) {
    try { S.nb = fn(S.nb); } catch (e) { toast(e.message); return false; }
    saveNotebook();
    if (what) log("notebook", what);
    renderInvestigate();
    return true;
  }
  function renderInvestigate() {
    var pane = clear($("investigatePane"));
    if (!S.ds) return;
    var nb = S.nb;
    var grid = h("div", { class: "pane-grid" });
    pane.appendChild(h("p", { class: "note" }, "Investigation notebook for ", h("b", null, S.ds.dataset.title), ". Started " + nb.created_at.slice(0, 10) + " on fingerprint " + shortFp(nb.dataset_fingerprint) + ". " + (S.storageOk ? "Saved in this browser only." : "Browser storage is unavailable: this notebook will be lost on reload.")));
    pane.appendChild(h("p", { class: "note" }, h("span", { class: "layer observed" }, "OBSERVED"), " from sources · ", h("span", { class: "layer derived" }, "DERIVED"), " computed · ", h("span", { class: "layer hypothesized" }, "HYPOTHESIZED"), " candidate explanations · ", h("span", { class: "layer analyst" }, "ANALYST-ASSESSED"), " your judgement"));
    pane.appendChild(grid);

    var q = h("textarea", { "aria-label": "Investigative question", maxlength: "4000" }, nb.question);
    var sc = h("textarea", { "aria-label": "Scope note", maxlength: "4000" }, nb.scope_note);
    var c1 = h("section", { class: "card" }, h("h3", null, "Question and scope"),
      h("label", { class: "field" }, h("span", null, "Investigative question"), q),
      h("label", { class: "field" }, h("span", null, "Scope note (what is in and out of bounds)"), sc),
      btn("Save question", function () { nbUpdate(function (n) { return C.Notebook.setQuestion(n, q.value, sc.value, new Date()); }, "Question saved"); toast("Saved"); }, "sm primary"));
    grid.appendChild(c1);

    var hl = h("ul", { class: "list" });
    nb.hypotheses.forEach(function (hy) {
      hl.appendChild(h("li", null, h("span", { class: "layer hypothesized" }, "HYP"), h("div", { class: "grow" }, h("b", null, hy.label), hy.statement ? h("div", { class: "note" }, hy.statement) : null),
        btn("Remove", function () { nbUpdate(function (n) { return C.Notebook.removeHypothesis(n, hy.id, new Date()); }, "Removed hypothesis " + hy.id); }, "sm quiet")));
    });
    var hLabel = h("input", { type: "text", placeholder: "Short label, e.g. H2 Unrelated operators", maxlength: "200", "aria-label": "Hypothesis label" });
    var hStmt = h("textarea", { placeholder: "What would have to be true", "aria-label": "Hypothesis statement" });
    grid.appendChild(h("section", { class: "card" }, h("h3", null, "Competing hypotheses ", h("span", { class: "layer hypothesized" }, "HYPOTHESIZED")),
      nb.hypotheses.length ? hl : h("p", { class: "note" }, "Add at least two alternative explanations. A hypothesis is a candidate, not a finding."),
      h("div", { class: "field" }, hLabel, hStmt),
      btn("Add hypothesis", function () { if (nbUpdate(function (n) { return C.Notebook.addHypothesis(n, { label: hLabel.value, statement: hStmt.value }, new Date()); }, "Hypothesis added")) toast("Hypothesis added"); }, "sm primary")));

    grid.appendChild(matrixCard());

    grid.appendChild(listCard("Assumptions", "assumptions", "State what you are taking as given without proof."));
    grid.appendChild(listCard("Unresolved questions", "open_questions", "What would change your assessment if answered?"));

    var al = h("ul", { class: "list" });
    nb.annotations.forEach(function (a) {
      al.appendChild(h("li", null, h("div", { class: "grow" }, citeBtn(a.target), " ", a.text, h("div", { class: "note" }, a.created_at)),
        btn("Delete", function () { nbUpdate(function (n) { return C.Notebook.removeAnnotation(n, a.id, new Date()); }, "Annotation deleted"); }, "sm quiet")));
    });
    grid.appendChild(h("section", { class: "card" }, h("h3", null, "Annotations ", h("span", { class: "layer analyst" }, "ANALYST-ASSESSED")),
      nb.annotations.length ? al : h("p", { class: "note" }, "Use Annotate in the inspector to record a judgement about any record.")));

    grid.appendChild(conclusionCard());
  }

  function listCard(title, key, hint) {
    var ul = h("ul", { class: "list" });
    S.nb[key].forEach(function (it) {
      var cb = h("input", { type: "checkbox", checked: it.status !== "open", "aria-label": "Resolved", onchange: function () { nbUpdate(function (n) { return C.Notebook.toggleItem(n, key, it.id, new Date()); }); } });
      ul.appendChild(h("li", { class: it.status === "open" ? null : "done" }, cb, h("div", { class: "grow" }, it.text)));
    });
    var inp = h("input", { type: "text", maxlength: "4000", placeholder: hint, "aria-label": "New " + title.toLowerCase().replace(/s$/, "") });
    return h("section", { class: "card" }, h("h3", null, title), S.nb[key].length ? ul : h("p", { class: "note" }, hint),
      h("div", { class: "row" }, h("div", { class: "grow" }, inp), btn("Add", function () { nbUpdate(function (n) { return C.Notebook.addItem(n, key, inp.value, new Date()); }, title + " updated"); }, "sm")));
  }

  function matrixCard() {
    var nb = S.nb;
    var card = h("section", { class: "card wide" }, h("h3", null, "Hypothesis–evidence matrix ", h("span", { class: "layer analyst" }, "ANALYST-ASSESSED")));
    if (!nb.evidence.length || !nb.hypotheses.length) {
      card.appendChild(h("p", { class: "note" }, !nb.hypotheses.length ? "Add hypotheses, then attach evidence from the inspector (Add to investigation)." : "Attach evidence from the inspector (Add to investigation) to fill the matrix."));
      if (nb.evidence.length) card.appendChild(h("p", { class: "note" }, plural(nb.evidence.length, "record") + " attached."));
      return card;
    }
    card.appendChild(h("p", { class: "note" }, "Mark each record as consistent, inconsistent or neutral against each hypothesis. Inconsistent evidence usually discriminates better than consistent evidence. Counts are not probabilities, and records from the same source group are not independent."));
    var table = h("table", { class: "matrix" });
    var head = h("tr", null, h("th", { scope: "col" }, "Evidence"), h("th", { scope: "col" }, "Source group"));
    nb.hypotheses.forEach(function (hy) { head.appendChild(h("th", { scope: "col" }, hy.label)); });
    head.appendChild(h("th", { scope: "col" }, h("span", { class: "sr" }, "Remove")));
    table.appendChild(h("thead", null, head));
    var tb = h("tbody");
    nb.evidence.forEach(function (ev) {
      var o = S.idx.observation.get(ev.id), s = o && S.idx.source.get(o.source_id);
      var tr = h("tr", null, h("th", { scope: "row" }, citeBtn(ev.id), h("div", { class: "note" }, o ? truncate(o.excerpt, 110) : "Missing from the current dataset")),
        h("td", { class: "mono" }, s ? s.independence_group + " · " + s.assessment.reliability : "—"));
      nb.hypotheses.forEach(function (hy) {
        var v = (nb.matrix[hy.id] || {})[ev.id] || "";
        var sel = h("select", { "aria-label": hy.label + " vs " + ev.id, onchange: function () {
          nbUpdate(function (n) { return C.Notebook.setAssessment(n, hy.id, ev.id, sel.value || null, new Date()); }, "Assessed " + ev.id + " against " + hy.id);
        } }, h("option", { value: "", selected: !v }, "— not assessed"), h("option", { value: "consistent", selected: v === "consistent" }, "C · consistent"),
          h("option", { value: "inconsistent", selected: v === "inconsistent" }, "I · inconsistent"), h("option", { value: "neutral", selected: v === "neutral" }, "N · neutral"));
        tr.appendChild(h("td", { class: v ? "c-" + v : null }, sel));
      });
      tr.appendChild(h("td", null, btn("Remove", function () { nbUpdate(function (n) { return C.Notebook.detachEvidence(n, ev.id, new Date()); }, "Detached " + ev.id); }, "sm quiet")));
      tb.appendChild(tr);
    });
    table.appendChild(tb);
    var sums = C.matrixSummary(nb, S.idx);
    var foot = h("tr", null, h("td", null, "Counts"), h("td", null, ""));
    sums.forEach(function (sm) { foot.appendChild(h("td", null, "C " + sm.counts.consistent + " · I " + sm.counts.inconsistent + " · N " + sm.counts.neutral + " · ? " + sm.counts.unassessed, h("div", null, "inconsistent from " + plural(sm.inconsistentGroups, "group")))); });
    foot.appendChild(h("td"));
    table.appendChild(h("tfoot", null, foot));
    card.appendChild(h("div", { class: "matrix-wrap" }, table));
    return card;
  }

  function conclusionCard() {
    var nb = S.nb;
    var card = h("section", { class: "card wide" }, h("h3", null, "Conclusion ", h("span", { class: "layer analyst" }, "ANALYST-ASSESSED")));
    var c = nb.conclusion;
    if (c && c.state === "recorded") {
      var hy = nb.hypotheses.filter(function (x) { return x.id === c.hypothesis_id; })[0];
      card.appendChild(h("div", { class: "conclusion" },
        h("p", { class: "label" }, "Recorded " + c.recorded_at),
        h("p", null, h("b", null, hy ? hy.label : "No hypothesis selected (insufficient evidence)")),
        h("p", null, c.text), h("p", { class: "note" }, "Rationale: " + c.rationale)));
      card.appendChild(h("div", { class: "row" }, btn("Reopen conclusion…", function () {
        promptText("Reopen conclusion", "Reason for reopening", "The current conclusion stays in the history. Say what changed.", function (reason) {
          nbUpdate(function (n) { return C.Notebook.reopenConclusion(n, reason, new Date()); }, "Conclusion reopened");
        });
      }), btn("Go to Brief", function () { setMode("brief"); }, "sm primary")));
    } else {
      if (c && c.state === "reopened") card.appendChild(h("div", { class: "conclusion reopened" }, h("p", { class: "label" }, "Reopened " + (c.reopened_at || "")), h("p", null, "Previous: " + c.text)));
      var sel = h("select", { "aria-label": "Selected hypothesis" }, h("option", { value: "" }, "None — the evidence is insufficient to choose"),
        nb.hypotheses.map(function (x) { return h("option", { value: x.id }, x.label); }));
      var text = h("textarea", { "aria-label": "Conclusion", placeholder: "What you conclude, in one or two sentences" });
      var why = h("textarea", { "aria-label": "Rationale", placeholder: "Based on what? Cite the decisive evidence and the inconsistencies." });
      card.appendChild(h("label", { class: "field" }, h("span", null, "Hypothesis best supported"), sel));
      card.appendChild(h("label", { class: "field" }, h("span", null, "Conclusion"), text));
      card.appendChild(h("label", { class: "field" }, h("span", null, "Rationale (required)"), why));
      card.appendChild(btn("Record conclusion", function () {
        if (nbUpdate(function (n) { return C.Notebook.recordConclusion(n, { hypothesis_id: sel.value || null, text: text.value, rationale: why.value }, new Date()); }, "Conclusion recorded")) toast("Conclusion recorded");
      }, "sm primary"));
    }
    if (nb.conclusion_history.length) {
      card.appendChild(h("p", { class: "label" }, "History"));
      card.appendChild(h("ul", { class: "lim" }, nb.conclusion_history.map(function (x) { return h("li", null, (x.at || "") + " — " + x.action + (x.reason ? ": " + x.reason : "") + (x.text ? " (was: " + truncate(x.text, 90) + ")" : "")); })));
    }
    return card;
  }

  /* ───────────────────────── compare mode ───────────────────────── */
  function loadCompareText(text, origin) {
    var r = C.parseDataset(text);
    if (!r.ok) { showErrors("Snapshot not loaded", r.errors); log("error", "Comparison snapshot rejected: " + plural(r.errors.length, "error")); return; }
    var diff = C.diffDatasets(S.ds, r.dataset);
    S.compare = { ds: r.dataset, idx: C.buildIndex(r.dataset), diff: diff, origin: origin, base: S.fp, fp: r.fingerprint };
    log("data", "Comparison snapshot v" + r.dataset.dataset.version + " loaded: +" + diff.totals.added + " / −" + diff.totals.notPresent + " / ~" + diff.totals.modified);
    renderCompare(); renderInspector();
  }
  function renderCompare() {
    var pane = clear($("comparePane"));
    if (!S.ds) return;
    if (!S.compare) {
      var card = h("section", { class: "card" }, h("h3", null, "Snapshot comparison"),
        h("p", null, "Compare the loaded dataset (v" + S.ds.dataset.version + ", as of " + (S.ds.dataset.as_of || "unknown") + ") with another snapshot of the same dataset. Records are matched by identifier."),
        h("p", { class: "note" }, "Only one snapshot is loaded, so no history is available yet."));
      var acts = h("div", { class: "row" });
      if (S.ds.dataset.id === BUNDLED.id && S.ds.dataset.version === "1.0.0") acts.appendChild(btn("Load bundled later snapshot (v1.1.0)", function () {
        fetchText(BUNDLED.v2).then(function (t) { loadCompareText(t, { kind: "bundled", name: "lookalike-domain-v2.json" }); }, function (e) { toast("Could not load snapshot: " + e.message); });
      }, "sm primary"));
      acts.appendChild(btn("Import a snapshot file…", function () { $("fileCompare").click(); }));
      card.appendChild(acts);
      pane.appendChild(card);
      return;
    }
    var d = S.compare.diff;
    var head = h("section", { class: "card" }, h("h3", null, "Snapshot comparison"),
      h("p", null, "From v" + d.from.version + " (as of " + (d.from.as_of || "unknown") + ", " + shortFp(d.from.fingerprint) + ") to v" + d.to.version + " (as of " + (d.to.as_of || "unknown") + ", " + shortFp(d.to.fingerprint) + ")."),
      d.sameDataset ? null : h("p", { class: "note warn" }, "The dataset IDs differ. Matching by record ID may pair unrelated records."),
      h("p", null, h("b", null, d.totals.added + " added · " + d.totals.notPresent + " not present · " + d.totals.modified + " modified")),
      h("ul", { class: "lim" }, d.caveats.map(function (c) { return h("li", null, c); })),
      h("div", { class: "row" },
        btn("Switch workspace to v" + d.to.version, function () { var cmp = S.compare; install({ dataset: cmp.ds, fingerprint: cmp.fp, warnings: [] }, { kind: cmp.origin.kind, name: cmp.origin.name }); setMode("explore"); toast("Now working on v" + cmp.ds.dataset.version); }, "sm"),
        btn("Clear comparison", function () { S.compare = null; renderCompare(); renderInspector(); }, "sm quiet")));
    pane.appendChild(head);
    var grid = h("div", { class: "pane-grid" });
    pane.appendChild(grid);
    var asOfA = S.ds.dataset.as_of;
    ["observations", "relationships", "entities", "claims", "sources", "merge_candidates"].forEach(function (c) {
      var x = d.collections[c];
      if (!x.added.length && !x.notPresent.length && !x.modified.length) return;
      var card = h("section", { class: "card diff-col" }, h("h3", null, c.replace("_", " ")));
      if (x.added.length) {
        card.appendChild(h("h4", null, "Added in v" + d.to.version + " (" + x.added.length + ")"));
        x.added.forEach(function (id) {
          var rec = (S.compare.ds[c] || []).filter(function (r) { return r.id === id; })[0];
          var it = h("div", { class: "diff-item" }, h("span", { class: "cite" }, id), " ", describeRecord(c, rec, S.compare.idx));
          if (c === "observations") {
            if (!rec.observed_at) it.appendChild(h("p", { class: "why" }, "Observation time unknown: cannot tell whether this is new activity."));
            else if (asOfA && Date.parse(rec.observed_at) <= Date.parse(asOfA)) it.appendChild(h("p", { class: "why" }, "Newly collected, not newly occurring: observed " + fmtTime(rec.observed_at) + ", before the earlier snapshot's as-of date; collected " + fmtTime(rec.collected_at) + "."));
            else it.appendChild(h("p", { class: "why" }, "Observed " + fmtTime(rec.observed_at) + ", after the earlier snapshot's as-of date."));
          }
          card.appendChild(it);
        });
      }
      if (x.notPresent.length) {
        card.appendChild(h("h4", null, "Not present in v" + d.to.version + " (" + x.notPresent.length + ")"));
        x.notPresent.forEach(function (id) {
          card.appendChild(h("div", { class: "diff-item" }, citeBtn(id), " ", describeRecord(c, (S.ds[c] || []).filter(function (r) { return r.id === id; })[0], S.idx),
            h("p", { class: "why" }, "Absent from the later snapshot. This does not show the fact was deleted or stopped being true.")));
        });
      }
      if (x.modified.length) {
        card.appendChild(h("h4", null, "Modified (" + x.modified.length + ")"));
        x.modified.forEach(function (m) {
          var it = h("div", { class: "diff-item" }, citeBtn(m.id), " ", describeRecord(c, m.after, S.compare.idx));
          if (m.fields.length === 1 && m.fields[0] === "extraction") it.appendChild(h("p", { class: "why" }, "Extraction change only (" + (m.before.extraction.version || "?") + " → " + (m.after.extraction.version || "?") + "): same source record, different processing."));
          if (m.fields.indexOf("review") !== -1) it.appendChild(h("p", { class: "why" }, "Analyst review changed: " + m.before.review + " → " + m.after.review + "."));
          if (m.fields.indexOf("evidence") !== -1) {
            var bs = m.before.evidence.supporting, as = m.after.evidence.supporting;
            var plus = as.filter(function (z) { return bs.indexOf(z) === -1; }), minus = bs.filter(function (z) { return as.indexOf(z) === -1; });
            it.appendChild(h("p", { class: "why" }, "Supporting evidence: " + (plus.length ? "+" + plus.join(", +") : "") + (plus.length && minus.length ? "; " : "") + (minus.length ? "−" + minus.join(", −") : "") + (!plus.length && !minus.length ? "contradicting list changed" : "") + "."));
          }
          it.appendChild(h("p", { class: "chg" }, "Changed: " + m.fields.join(", ")));
          card.appendChild(it);
        });
      }
      grid.appendChild(card);
    });
  }
  function describeRecord(c, rec, idx) {
    if (!rec) return "";
    if (c === "observations") return truncate(rec.excerpt, 120);
    if (c === "relationships") { var a = idx.entity.get(rec.from), b = idx.entity.get(rec.to); return (a ? a.label : rec.from) + " → " + rec.type + " → " + (b ? b.label : rec.to); }
    if (c === "entities") return rec.label + " (" + rec.type + ")";
    if (c === "claims") return truncate(rec.statement, 120);
    if (c === "sources") return rec.title;
    return (rec.entities || []).join(" + ");
  }

  /* ───────────────────────── brief + exports ───────────────────────── */
  function includedRuns() { var out = []; S.findings.forEach(function (r) { if (r.include) out.push(r); }); return out; }
  function extraLimitations() {
    var out = [];
    if (S.origin && S.origin.kind === "import") out.push("Dataset imported from a local file (" + S.origin.name + "); its sources were not verified by this workspace.");
    if (S.warnings.length) out.push("Import produced " + plural(S.warnings.length, "warning") + " (unknown keys ignored).");
    var stale = S.findings.get(S.metricsRunId);
    if (stale && stale.include && stale.scopeKey !== scopeKey()) out.push("The included graph-metrics run was computed on a different scope than the current view.");
    return out;
  }
  function makeBrief() {
    return C.buildBrief({ dataset: S.ds, index: S.idx, notebook: S.nb, runs: includedRuns(), now: new Date(), viewSummary: S.view.layout + " layout; " + describeScope(), extraLimitations: extraLimitations() });
  }
  function renderBrief() {
    var pane = clear($("briefPane"));
    if (!S.ds) return;
    var b = makeBrief();
    var top = h("section", { class: "card" }, h("h3", null, "Brief and exports"));
    top.appendChild(h("p", { class: b.ok ? "note" : "note err", role: "status" }, b.ok ? "Every citation (" + b.citations.cited.length + ") resolves to a record in this dataset." + (b.missingRefs.length ? " " + plural(b.missingRefs.length, "reference") + " to missing records are named but not cited." : "") : "Export blocked: citations that do not exist: " + b.citations.invalid.join(", ")));
    var runs = []; S.findings.forEach(function (r) { runs.push(r); });
    if (runs.length) {
      top.appendChild(h("p", { class: "label" }, "Analyses in Methods"));
      runs.forEach(function (r) {
        var cb = h("input", { type: "checkbox", checked: r.include, onchange: function () { r.include = cb.checked; renderBrief(); } });
        top.appendChild(h("label", { class: "check" }, cb, r.name + " · " + r.id + " · " + truncate(r.summary, 70)));
      });
    } else top.appendChild(h("p", { class: "note" }, "No analyses run yet. Path analysis and graph metrics you run appear here and in Methods."));
    var ex = h("div", { class: "exports" },
      btn("Brief (.md)", function () { if (!b.ok) { toast("Fix invalid citations first"); return; } var bb = makeBrief(); download(fileBase("brief") + ".md", "text/markdown", bb.markdown); }, "sm primary", { disabled: !b.ok }),
      btn("Graph JSON (versioned)", function () { download(fileBase("graph") + ".json", "application/json", JSON.stringify(C.exportDataset(S.ds, { now: new Date() }), null, 2)); }),
      btn("Entities CSV", function () { download(fileBase("entities") + ".csv", "text/csv", C.entitiesCSV(S.ds)); }),
      btn("Relationships CSV", function () { download(fileBase("relationships") + ".csv", "text/csv", C.relationshipsCSV(S.ds)); }),
      btn("Evidence manifest", function () { exportManifest(S.nb.evidence.map(function (e) { return e.id; }), "investigation"); }),
      btn("View state", function () { download(fileBase("view") + ".json", "application/json", JSON.stringify(viewState(), null, 2)); }),
      btn("Graph image (.svg)", exportSvg));
    top.appendChild(ex);
    top.appendChild(h("p", { class: "note" }, "Exports omit fields restricted by the dataset's export policy (" + (S.ds.dataset.export_policy.restricted_attribute_keys.join(", ") || "none") + "). CSV cells that a spreadsheet would run as formulas are prefixed with an apostrophe. Files are generated in this browser; nothing is uploaded."));
    pane.appendChild(top);
    var doc = h("article", { class: "card brief-doc", "aria-label": "Brief preview" });
    renderMarkdown(doc, b.markdown);
    pane.appendChild(doc);
  }
  function renderMarkdown(container, md) {
    var lines = md.split("\n"), list = null, sub = null, table = null;
    function inline(text) {
      var out = [], re = /\[ref:([^\]\s]{1,128})\]|`([^`]+)`/g, last = 0, m;
      while ((m = re.exec(text)) !== null) {
        if (m.index > last) out.push(text.slice(last, m.index));
        if (m[1]) out.push(citeBtn(m[1])); else out.push(h("code", null, m[2]));
        last = re.lastIndex;
      }
      if (last < text.length) out.push(text.slice(last));
      return out.map(function (x) { return typeof x === "string" ? x.replace(/&lt;/g, "<").replace(/&gt;/g, ">") : x; });
    }
    function endBlocks() { list = null; sub = null; table = null; }
    lines.forEach(function (line) {
      if (/^# /.test(line)) { endBlocks(); container.appendChild(h("h2", null, inline(line.slice(2)))); return; }
      if (/^## /.test(line)) { endBlocks(); container.appendChild(h("h3", null, inline(line.slice(3)))); return; }
      if (/^### /.test(line)) { endBlocks(); container.appendChild(h("h4", null, inline(line.slice(4)))); return; }
      if (/^> /.test(line)) { endBlocks(); container.appendChild(h("blockquote", null, inline(line.slice(2)))); return; }
      if (/^\|/.test(line)) {
        list = null;
        if (/^\|[-| ]+\|$/.test(line)) return;
        if (!table) { table = h("table"); container.appendChild(table); }
        var cells = line.replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map(function (c) { return c.trim().replace(/\\\|/g, "|"); });
        var tr = h("tr");
        cells.forEach(function (c) { tr.appendChild(h(table.children.length ? "td" : "th", null, inline(c))); });
        table.appendChild(tr);
        return;
      }
      if (/^ {2}- /.test(line) && list) {
        if (!sub) { sub = h("ul"); (list.lastChild || list).appendChild(sub); }
        sub.appendChild(h("li", null, inline(line.slice(4))));
        return;
      }
      if (/^- /.test(line)) {
        table = null; sub = null;
        if (!list) { list = h("ul"); container.appendChild(list); }
        list.appendChild(h("li", null, inline(line.slice(2))));
        return;
      }
      endBlocks();
      if (/^---$/.test(line)) { container.appendChild(h("hr")); return; }
      if (!line.trim()) return;
      if (/^_.*_$/.test(line)) { container.appendChild(h("p", { class: "note" }, inline(line.slice(1, -1)))); return; }
      container.appendChild(h("p", null, inline(line)));
    });
  }
  function fileBase(kind) { return "sentinel-" + kind + "-" + S.ds.dataset.id + "-v" + S.ds.dataset.version + "-" + shortFp(S.fp) + "-" + stamp(); }
  function download(name, mime, text) {
    var blob = new Blob([text], { type: mime + ";charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = h("a", { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1500);
    log("export", "Exported " + name + " (" + text.length + " characters)");
    toast("Saved " + name);
  }
  function exportManifest(ids, label) {
    if (!ids.length) { toast("No evidence to export"); return; }
    download(fileBase("evidence-" + String(label).replace(/[^A-Za-z0-9_-]/g, "_")) + ".json", "application/json", JSON.stringify(C.evidenceManifest(S.ds, S.idx, ids, { now: new Date() }), null, 2));
  }
  var EXPORT_CSS = [
    "text{font-family:system-ui,-apple-system,'Segoe UI',sans-serif}",
    ".g-ring{fill:none;stroke:#2f3b49;stroke-dasharray:2 6}.g-ring-label,.g-sector-label{fill:#7a8796;font-size:11px;font-weight:600}",
    ".edge{fill:none;stroke:#5d6d80;stroke-width:1.4}.rv-e-confirmed{stroke:#3fa596}.rv-e-unreviewed{stroke:#7a8796;stroke-dasharray:6 4}.rv-e-disputed{stroke:#fbbf24;stroke-dasharray:2 3}.rv-e-rejected{stroke:#f87171;stroke-dasharray:1 4}",
    ".edge-hit,.ev-mark,.ev-count,.halo,.pin{display:none}.edge-g.sel .edge{stroke:#38bdf8;stroke-width:2.6}.edge-g.path .edge{stroke:#a78bfa;stroke-width:3}.edge-g.dim .edge{opacity:.2}",
    ".edge-label{display:none}.edge-g.sel .edge-label,.edge-g.path .edge-label{display:block;fill:#a3afbd;font-size:10.5px}",
    ".shape{fill:#171e27;stroke-width:1.6;stroke:currentColor}.glyph{fill:currentColor;font-size:8.5px;font-weight:700;text-anchor:middle;dominant-baseline:central}",
    ".lbl{fill:#e6edf3;font-size:11.5px}.node.dim{opacity:.3}.node.sel .shape{stroke:#38bdf8;stroke-width:3}.node.path .shape{stroke:#a78bfa;stroke-width:2.6}.merged{fill:none;stroke:#7a8796}",
    ".t-organization{color:#c3cfdd}.t-domain{color:#6cb6ff}.t-ip{color:#b9c99a}.t-certificate{color:#d9b98a}.t-document{color:#a8b3c4}.t-system{color:#86c5b9}.t-account{color:#d1a3a3}.t-topic{color:#9aa7b6}.t-person{color:#e6edf3}.t-other{color:#7a8796}"
  ].join("");
  function exportSvg() {
    var src = $("graph");
    if (!src.querySelector("#vp")) { toast("Nothing to export"); return; }
    var c = canvasSize();
    var clone = src.cloneNode(true);
    clone.setAttribute("xmlns", SVGNS);
    clone.setAttribute("width", String(Math.round(c.w)));
    clone.setAttribute("height", String(Math.round(c.h + 40)));
    clone.setAttribute("viewBox", "0 0 " + Math.round(c.w) + " " + Math.round(c.h + 40));
    clone.removeAttribute("role"); clone.removeAttribute("aria-label"); clone.removeAttribute("aria-roledescription");
    clone.querySelectorAll("[tabindex]").forEach(function (n) { n.removeAttribute("tabindex"); });
    var style = document.createElementNS(SVGNS, "style");
    style.textContent = EXPORT_CSS;
    clone.insertBefore(style, clone.firstChild);
    clone.insertBefore(sv("rect", { x: 0, y: 0, width: "100%", height: "100%", fill: "#07090c" }), style.nextSibling);
    clone.appendChild(sv("text", { x: 10, y: Math.round(c.h + 18), fill: "#a3afbd", "font-size": 11 }, S.ds.dataset.title + " · v" + S.ds.dataset.version + " · " + S.fp + (S.ds.dataset.synthetic ? " · SYNTHETIC" : "")));
    clone.appendChild(sv("text", { x: 10, y: Math.round(c.h + 33), fill: "#7a8796", "font-size": 10 }, "Scope: " + truncate(describeScope(), 180) + " · exported " + nowIso()));
    download(fileBase("graph-image") + ".svg", "image/svg+xml", new XMLSerializer().serializeToString(clone));
  }

  /* ───────────────────────── dialogs ───────────────────────── */
  function openDialog(id) { var d = $(id); if (!d.open) d.showModal(); return d; }
  function showErrors(title, errors, note) {
    $("dlgErrorsTitle").textContent = title;
    var b = clear($("errorsBody"));
    if (note) b.appendChild(h("p", { class: "note" }, note));
    b.appendChild(h("ul", { class: "errlist" }, errors.slice(0, 50).map(function (e) { return h("li", null, e.path + " — " + e.message); })));
    if (errors.length > 50) b.appendChild(h("p", { class: "note" }, "…and " + (errors.length - 50) + " more."));
    b.appendChild(h("p", { class: "note" }, "The format is described in sentinel-workspace/README.md (schema \"" + C.SCHEMA + "\")."));
    openDialog("dlgErrors");
  }
  var promptCb = null;
  function promptText(title, label, note, cb) {
    $("dlgPromptTitle").textContent = title;
    $("promptLabel").textContent = label;
    $("promptNote").textContent = note || "";
    $("promptInput").value = "";
    promptCb = cb;
    openDialog("dlgPrompt");
    $("promptInput").focus();
  }
  function bindPrompt() {
    $("promptForm").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var v = $("promptInput").value.trim();
      if (!v) { $("promptInput").focus(); return; }
      $("dlgPrompt").close();
      var cb = promptCb; promptCb = null;
      if (cb) cb(v);
    });
    $("promptCancel").addEventListener("click", function () { promptCb = null; $("dlgPrompt").close(); });
  }

  function renderDataDialog() {
    var b = clear($("dataBody"));
    if (S.ds) {
      var d = S.ds.dataset;
      b.appendChild(h("dl", { class: "kv" },
        h("dt", null, "Title"), h("dd", null, d.title),
        h("dt", null, "Dataset ID"), h("dd", { class: "mono" }, d.id),
        h("dt", null, "Version"), h("dd", null, d.version + " · as of " + (d.as_of || "unknown")),
        h("dt", null, "Synthetic"), h("dd", null, d.synthetic ? "Yes. Every record is fictional." : "No — declared as real data by its author. The workspace has not verified it."),
        h("dt", null, "Fingerprint"), h("dd", { class: "mono" }, S.fp),
        h("dt", null, "Loaded from"), h("dd", null, (S.origin.kind === "bundled" ? "bundled file " : "imported file ") + S.origin.name + (S.origin.bytes ? " · " + S.origin.bytes + " bytes" : "")),
        h("dt", null, "Records"), h("dd", null, ["sources", "entities", "observations", "relationships", "claims", "merge_candidates"].map(function (c) { return S.ds[c].length + " " + c.replace("_", " "); }).join(" · ")),
        h("dt", null, "Undated"), h("dd", null, plural(S.idx.undatedObservations, "observation") + " without an observation time")));
      if (d.description) b.appendChild(h("p", { class: "note" }, d.description));
    }
    b.appendChild(h("div", { class: "row" },
      btn("Load bundled training dataset", function () { $("dlgData").close(); loadBundled("v1"); }, "sm"),
      btn("Import dataset (.json, ≤ 5 MB)…", function () { $("fileDataset").click(); }, "sm primary"),
      btn("Import view state…", function () { $("fileView").click(); }, "sm")));
    b.appendChild(h("p", { class: "note" }, "Imports are validated against schema \"" + C.SCHEMA + "\" before anything changes: identifiers, references, time fields (null means unknown), source links (http/https only) and size limits (" + C.LIMITS.maxEntities + " entities, " + C.LIMITS.maxRelationships + " relationships). Imported data stays in this tab's memory."));
    b.appendChild(h("p", { class: "note" }, "Format reference: sentinel-workspace/README.md in the repository."));
  }
  function renderHandlingDialog() {
    var b = clear($("handlingBody"));
    b.appendChild(h("h3", null, "Network"));
    b.appendChild(h("ul", null,
      h("li", null, "This page loads only its own files from this site: the page, one stylesheet, two scripts and the bundled synthetic dataset."),
      h("li", null, "It contacts no other service. Its Content-Security-Policy limits connections to this origin. There is no analytics or telemetry."),
      h("li", null, "Source links inside a dataset open only when you click them, in a new tab, without a referrer.")));
    b.appendChild(h("h3", null, "AI"));
    b.appendChild(h("ul", null, h("li", null, "No AI model is configured. Summaries come from fixed rules over the records and cite record IDs. Nothing is sent to a model.")));
    b.appendChild(h("h3", null, "Storage and retention"));
    var keys = storeKeys();
    b.appendChild(h("ul", null,
      h("li", null, "Imported datasets stay in this tab's memory and are discarded on reload."),
      h("li", null, "The investigation notebook (question, hypotheses, assessments, annotations, conclusions, merge decisions) and view state are saved in this browser's local storage, per dataset ID, until you delete them."),
      h("li", null, "Browser storage can be read and edited by anyone using this browser profile. It is not tamper-evident, and exported briefs are not signed."),
      h("li", null, "Session activity is UI history only. It is not an application event log or a security audit record.")));
    b.appendChild(h("p", { class: "label" }, keys.length ? "Stored now" : "Nothing stored"));
    if (keys.length) b.appendChild(h("ul", { class: "errlist" }, keys.map(function (k) { return h("li", null, k.key + " · ~" + k.bytes + " bytes"); })));
    b.appendChild(h("h3", null, "Access control"));
    b.appendChild(h("ul", null, h("li", null, "This page has no accounts and enforces no permissions. Load only data you are allowed to view on this device.")));
    b.appendChild(btn("Delete all local workspace data…", function () {
      if (!window.confirm("Delete every saved notebook and view for Sentinel Workspace in this browser? This cannot be undone.")) return;
      storeClearAll();
      if (S.ds) { S.nb = C.createNotebook(S.ds, new Date()); refreshResolver(); recompute({ fit: true }); renderRail(); renderInspector(); renderMode(); }
      log("data", "Deleted all local workspace data");
      renderHandlingDialog();
      toast("Local workspace data deleted");
    }, "sm danger"));
  }

  /* ── search ── */
  var searchSel = 0, searchItems = [];
  function runSearch(q) {
    var list = clear($("searchResults"));
    q = q.trim().toLowerCase();
    searchItems = [];
    if (!S.ds || !q) { list.appendChild(h("li", { class: "note" }, "Type to search " + S.ds.entities.length + " entities and " + S.ds.observations.length + " evidence records.")); return; }
    function score(text) { text = String(text || "").toLowerCase(); var i = text.indexOf(q); return i === -1 ? -1 : (i === 0 ? 3 : 1) + (text === q ? 5 : 0); }
    var visible = new Set(S.graph ? S.graph.nodes.filter(function (n) { return !n.forced; }).map(function (n) { return n.id; }) : []);
    S.ds.entities.forEach(function (e) {
      var sc = Math.max(score(e.label), score(e.id), Math.max.apply(null, [-1].concat(e.aliases.map(score))), Math.max.apply(null, [-1].concat(e.original_ids.map(score))));
      if (sc >= 0) searchItems.push({ sc: sc + 2, kind: "entity", id: e.id, label: e.label, sub: TYPE_NAME[e.type] + " · " + e.id + (visible.has(S.resolver.canonicalOf(e.id)) ? "" : " · hidden by filters"), type: e.type });
    });
    S.ds.relationships.forEach(function (r) { var sc = Math.max(score(r.id), score(r.type)); if (sc >= 0) searchItems.push({ sc: sc, kind: "relationship", id: r.id, label: labelOf(r.id), sub: r.id }); });
    S.ds.claims.forEach(function (c) { var sc = Math.max(score(c.id), score(c.statement)); if (sc >= 0) searchItems.push({ sc: sc, kind: "claim", id: c.id, label: truncate(c.statement, 90), sub: "Claim · " + c.id }); });
    S.ds.observations.forEach(function (o) { var sc = Math.max(score(o.id), score(o.excerpt)); if (sc >= 0) searchItems.push({ sc: sc - 1, kind: "observation", id: o.id, label: truncate(o.excerpt, 90), sub: "Evidence · " + o.id }); });
    S.ds.sources.forEach(function (s) { var sc = Math.max(score(s.id), score(s.title)); if (sc >= 0) searchItems.push({ sc: sc, kind: "source", id: s.id, label: s.title, sub: "Source · " + s.id }); });
    searchItems.sort(function (a, b) { return b.sc - a.sc || (a.label < b.label ? -1 : 1); });
    searchItems = searchItems.slice(0, 40);
    searchSel = 0;
    if (!searchItems.length) { list.appendChild(h("li", { class: "note" }, "No matches.")); return; }
    searchItems.forEach(function (it, i) {
      list.appendChild(h("li", { role: "presentation" }, h("button", { type: "button", role: "option", id: "sr-" + i, "aria-selected": String(i === 0), onclick: function () { chooseSearch(it); } },
        it.kind === "entity" ? h("span", { class: "tglyph t-" + it.type }, GLYPH[it.type]) : h("span", { class: "tag" }, it.kind.slice(0, 4)),
        h("span", null, it.label, h("div", { class: "sub" }, it.sub)))));
    });
    $("searchInput").setAttribute("aria-activedescendant", "sr-0");
  }
  function chooseSearch(it) {
    $("dlgSearch").close();
    if (S.mode !== "explore" && it.kind === "entity") setMode("explore");
    select({ kind: it.kind, id: it.id }, { center: true });
    log("view", "Opened " + it.id + " from search");
  }
  function openSearch() {
    if (!S.ds) return;
    openDialog("dlgSearch");
    $("searchInput").value = "";
    runSearch("");
    $("searchInput").focus();
  }
  function bindSearch() {
    $("searchInput").addEventListener("input", function () { runSearch($("searchInput").value); });
    $("searchInput").addEventListener("keydown", function (ev) {
      if (!searchItems.length) return;
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        searchSel = (searchSel + (ev.key === "ArrowDown" ? 1 : -1) + searchItems.length) % searchItems.length;
        document.querySelectorAll("#searchResults [role=option]").forEach(function (b, i) { b.setAttribute("aria-selected", String(i === searchSel)); if (i === searchSel) b.scrollIntoView({ block: "nearest" }); });
        $("searchInput").setAttribute("aria-activedescendant", "sr-" + searchSel);
      } else if (ev.key === "Enter") { ev.preventDefault(); chooseSearch(searchItems[searchSel]); }
    });
  }

  /* ───────────────────────── modes, mobile chrome ───────────────────────── */
  function setMode(mode) {
    S.mode = mode;
    $("app").setAttribute("data-mode", mode);
    document.querySelectorAll("#modes button").forEach(function (b) { if (b.dataset.mode === mode) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); });
    renderMode();
  }
  function renderMode() {
    ["explore", "investigate", "compare", "brief"].forEach(function (m) { $("view" + m.charAt(0).toUpperCase() + m.slice(1)).hidden = S.mode !== m; });
    if (S.mode === "investigate") renderInvestigate();
    if (S.mode === "compare") renderCompare();
    if (S.mode === "brief") renderBrief();
    if (S.mode === "explore" && S.ds) { requestAnimationFrame(function () { if (S.positions.size && !$("graph").querySelector("#vp")) renderGraph(); }); }
  }
  function renderLayoutSeg() {
    document.querySelectorAll("#layoutSeg button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.layout === S.view.layout)); });
  }
  function setRep(rep) {
    S.view.rep = rep;
    document.querySelectorAll("#repSeg button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.rep === rep)); });
    $("tables").hidden = rep !== "table";
    $("canvas").hidden = rep !== "graph";
    if (rep === "table") renderTables(); else requestAnimationFrame(fitView);
  }
  function setSheet(state) {
    $("app").setAttribute("data-sheet", state);
    $("sheetHandle").setAttribute("aria-label", "Inspector size: " + state + ". Activate to " + (state === "full" ? "shrink." : "expand."));
    updateDock();
  }
  function openSheetFor() { if (isMobile()) { var cur = $("app").getAttribute("data-sheet"); if (cur === "closed" || cur === "peek") setSheet("half"); } }
  function updateDock() { $("dockInspector").setAttribute("aria-expanded", String($("app").getAttribute("data-sheet") !== "closed")); }
  function openRail() { $("app").classList.add("rail-open"); $("dockFilters").setAttribute("aria-expanded", "true"); if (!$("scrim")) { var s = h("div", { class: "scrim", id: "scrim", onclick: closeRail }); document.body.appendChild(s); } $("railClose").focus(); }
  function closeRail() { $("app").classList.remove("rail-open"); $("dockFilters").setAttribute("aria-expanded", "false"); var s = $("scrim"); if (s) s.remove(); }
  function toggleActivity(force) {
    var p = $("activityPanel"), open = force === undefined ? p.hidden : force;
    p.hidden = !open;
    $("activity").classList.toggle("open", open);
    $("activityToggle").setAttribute("aria-expanded", String(open));
    if (open) renderActivity();
  }

  function bindSheet() {
    var handle = $("sheetHandle"), start = null;
    handle.addEventListener("pointerdown", function (ev) { start = { y: ev.clientY, t: Date.now() }; try { handle.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ } });
    handle.addEventListener("pointerup", function (ev) {
      if (!start) return;
      var dy = ev.clientY - start.y, cur = $("app").getAttribute("data-sheet");
      var order = ["peek", "half", "full"];
      var i = Math.max(0, order.indexOf(cur));
      if (Math.abs(dy) < 8) setSheet(order[(i + 1) % order.length]);
      else if (dy < 0) setSheet(order[Math.min(2, i + 1)]);
      else setSheet(i === 0 ? "closed" : order[i - 1]);
      start = null;
    });
    handle.addEventListener("keydown", function (ev) {
      var order = ["closed", "peek", "half", "full"], i = order.indexOf($("app").getAttribute("data-sheet"));
      if (ev.key === "ArrowUp") { ev.preventDefault(); setSheet(order[Math.min(3, i + 1)]); }
      if (ev.key === "ArrowDown") { ev.preventDefault(); setSheet(order[Math.max(0, i - 1)]); }
    });
  }
  function bindResizer() {
    var r = $("resizer"), dragging = false;
    function setW(w) {
      w = Math.max(300, Math.min(680, Math.round(w)));
      document.documentElement.style.setProperty("--insp-w", w + "px");
      r.setAttribute("aria-valuenow", String(w));
      return w;
    }
    var pref = storeGet("pref") || {};
    if (pref.inspW) setW(pref.inspW);
    if (pref.railCollapsed) { $("app").classList.add("rail-collapsed"); $("railCollapse").setAttribute("aria-expanded", "false"); $("railCollapse").textContent = "»"; }
    r.addEventListener("pointerdown", function (ev) { dragging = true; try { r.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ } });
    r.addEventListener("pointermove", function (ev) { if (dragging) setW(window.innerWidth - ev.clientX); });
    r.addEventListener("pointerup", function () { if (!dragging) return; dragging = false; savePref({ inspW: +r.getAttribute("aria-valuenow") }); fitView(); });
    r.addEventListener("keydown", function (ev) {
      var w = +r.getAttribute("aria-valuenow");
      if (ev.key === "ArrowLeft") { ev.preventDefault(); savePref({ inspW: setW(w + 20) }); }
      if (ev.key === "ArrowRight") { ev.preventDefault(); savePref({ inspW: setW(w - 20) }); }
    });
  }
  function savePref(patch) { storeSet("pref", Object.assign(storeGet("pref") || {}, patch)); }

  function bindGlobal() {
    document.querySelectorAll("#modes button").forEach(function (b) { b.addEventListener("click", function () { setMode(b.dataset.mode); }); });
    document.querySelectorAll("#repSeg button").forEach(function (b) { b.addEventListener("click", function () { setRep(b.dataset.rep); }); });
    document.querySelectorAll("#layoutSeg button").forEach(function (b) {
      b.addEventListener("click", function () {
        if (S.view.layout === b.dataset.layout) return;
        pushLayoutHistory("switched to " + b.dataset.layout);
        S.view.layout = b.dataset.layout;
        renderLayoutSeg(); computeLayout({ fit: true }); saveView(); renderRail();
        log("layout", "Layout: " + b.dataset.layout);
      });
    });
    $("btnBack").addEventListener("click", goBack);
    $("dockBack").addEventListener("click", goBack);
    $("btnUndoLayout").addEventListener("click", undoLayout);
    $("btnUndoLayout").disabled = true;
    $("btnFit").addEventListener("click", fitView);
    $("dockFit").addEventListener("click", function () { if (S.mode !== "explore") setMode("explore"); fitView(); });
    $("btnZoomIn").addEventListener("click", function () { zoomAt(1.25); });
    $("btnZoomOut").addEventListener("click", function () { zoomAt(0.8); });
    $("btnLegend").addEventListener("click", function () {
      var l = $("legend"), open = l.hidden;
      if (open) renderLegend();
      l.hidden = !open;
      $("btnLegend").setAttribute("aria-expanded", String(open));
    });
    $("btnSearch").addEventListener("click", openSearch);
    $("dockSearch").addEventListener("click", openSearch);
    $("dockFilters").addEventListener("click", function () { if ($("app").classList.contains("rail-open")) closeRail(); else openRail(); });
    $("dockInspector").addEventListener("click", function () { setSheet($("app").getAttribute("data-sheet") === "closed" ? "half" : "closed"); });
    $("railClose").addEventListener("click", closeRail);
    $("railCollapse").addEventListener("click", function () {
      var collapsed = $("app").classList.toggle("rail-collapsed");
      $("railCollapse").setAttribute("aria-expanded", String(!collapsed));
      $("railCollapse").textContent = collapsed ? "»" : "«";
      $("railCollapse").title = collapsed ? "Expand controls" : "Collapse controls";
      savePref({ railCollapsed: collapsed });
      requestAnimationFrame(fitView);
    });
    $("btnData").addEventListener("click", function () { renderDataDialog(); openDialog("dlgData"); });
    $("btnHandling").addEventListener("click", function () { renderHandlingDialog(); openDialog("dlgHandling"); });
    document.querySelectorAll("dialog [data-close]").forEach(function (b) { b.addEventListener("click", function () { b.closest("dialog").close(); }); });
    $("fileDataset").addEventListener("change", function (ev) { var f = ev.target.files[0]; ev.target.value = ""; if ($("dlgData").open) $("dlgData").close(); importDataset(f); });
    $("fileCompare").addEventListener("change", function (ev) { var f = ev.target.files[0]; ev.target.value = ""; readFileChecked(f, function (t) { loadCompareText(t, { kind: "import", name: f.name }); }); });
    $("fileView").addEventListener("change", function (ev) {
      var f = ev.target.files[0]; ev.target.value = "";
      readFileChecked(f, function (t) {
        var v; try { v = JSON.parse(t); } catch (e) { showErrors("View state not applied", [{ path: "$", message: "Not valid JSON." }]); return; }
        if ($("dlgData").open) $("dlgData").close();
        if (applyViewState(v)) { renderLayoutSeg(); recompute({ fit: true }); renderRail(); renderInspector(); }
      });
    });
    $("activityToggle").addEventListener("click", function () { toggleActivity(); });
    $("jobCancel").addEventListener("click", function () { cancelJob(); log("layout", "Layout job cancelled; previous positions kept"); toast("Layout cancelled"); });
    document.addEventListener("keydown", function (ev) {
      var tag = (ev.target.tagName || "").toLowerCase();
      var typing = tag === "input" || tag === "textarea" || tag === "select" || ev.target.isContentEditable;
      if (document.querySelector("dialog[open]")) return;
      if (ev.key === "/" && !typing) { ev.preventDefault(); openSearch(); return; }
      if (ev.altKey && ev.key === "ArrowLeft") { ev.preventDefault(); goBack(); return; }
      if (ev.key === "Escape") {
        if ($("app").classList.contains("rail-open")) { closeRail(); $("dockFilters").focus(); return; }
        if (!$("activityPanel").hidden && isMobile()) { toggleActivity(false); return; }
        if (isMobile() && $("app").getAttribute("data-sheet") !== "closed") { setSheet("closed"); return; }
        if (S.selection && !typing) select(null);
        return;
      }
      if (!typing && (ev.key === "f" || ev.key === "F") && S.mode === "explore") { fitView(); }
    });
    if (typeof ResizeObserver !== "undefined") {
      var lastSize = "";
      new ResizeObserver(function () {
        var c = canvasSize(), key = Math.round(c.w) + "x" + Math.round(c.h);
        if (key === lastSize) return;
        lastSize = key;
        /* Refit only while the user has not zoomed or panned by hand. */
        if (S.positions.size && Math.abs(S.zoom.k - S.fitK) < 1e-6 && S.mode === "explore") fitView();
      }).observe($("canvas"));
    }
    var resizeT = 0;
    window.addEventListener("resize", function () { clearTimeout(resizeT); resizeT = setTimeout(function () { if (S.mode === "explore" && S.view.rep === "graph") fitView(); if (!isMobile()) { closeRail(); } }, 150); });
    window.addEventListener("online", function () { if (!S.ds) loadBundled("v1"); });
  }

  /* ───────────────────────── boot ───────────────────────── */
  function boot() {
    try { localStorage.getItem(PREFIX + "probe"); } catch (e) { S.storageOk = false; }
    renderStorageState();
    bindCanvas(); bindGlobal(); bindSearch(); bindPrompt(); bindSheet(); bindResizer();
    log("data", "Workspace started (core " + C.CORE_VERSION + "); no external services are contacted");
    loadBundled("v1");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
}());
